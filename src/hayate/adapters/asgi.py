"""ASGI adapter: translates ASGI ``http`` / ``lifespan`` events to ``app.fetch()``.

Users never see ``scope`` / ``receive`` / ``send`` — the ``Hayate`` app is
itself an ASGI callable that delegates here, so ``uvicorn main:app`` works
out of the box.
"""

from __future__ import annotations

import inspect
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import TYPE_CHECKING, Any
from urllib.parse import quote

from ..abort import AbortSignal
from ..context import ExecutionContext
from ..request import Request
from ..url import URL

if TYPE_CHECKING:
    from ..app import Hayate
    from ..response import Response

type Receive = Callable[[], Awaitable[dict[str, Any]]]
type Send = Callable[[dict[str, Any]], Awaitable[None]]

_DEFAULT_SCHEME_PORTS = {"http": "80", "https": "443", "ws": "80", "wss": "443"}
# pchar set — keep valid path characters intact when re-encoding a decoded path.
_PATH_SAFE = "/:@!$&'()*+,;=~-._"


async def _request_body(receive: Receive, signal: AbortSignal) -> AsyncIterator[bytes]:
    while True:
        message = await receive()
        if message["type"] == "http.request":
            chunk = message.get("body", b"")
            if chunk:
                yield chunk
            if not message.get("more_body", False):
                return
        elif message["type"] == "http.disconnect":
            signal._abort("client disconnected")
            return


async def _call_hook(hook: Callable[[], Any]) -> None:
    result = hook()
    if inspect.isawaitable(result):
        await result


class ASGIAdapter:
    __slots__ = ("_app",)

    def __init__(self, app: Hayate) -> None:
        self._app = app

    async def __call__(self, scope: dict[str, Any], receive: Receive, send: Send) -> None:
        kind = scope["type"]
        if kind == "http":
            await self._http(scope, receive, send)
        elif kind == "lifespan":
            await self._lifespan(receive, send)
        else:
            raise RuntimeError(f"unsupported ASGI scope type: {kind!r} (websocket lands in v0.2)")

    # -- http -----------------------------------------------------------------

    async def _http(self, scope: dict[str, Any], receive: Receive, send: Send) -> None:
        signal = AbortSignal()
        request = Request(
            _build_url(scope),
            method=scope["method"],
            headers=[
                (name.decode("latin-1"), value.decode("latin-1"))
                for name, value in scope.get("headers", [])
            ],
            body=_request_body(receive, signal),
            signal=signal,
        )
        ctx = ExecutionContext()
        response = await self._app.fetch(request, ctx=ctx)
        try:
            await _send_response(scope, send, response)
        finally:
            await ctx._drain()

    # -- lifespan ----------------------------------------------------------------

    async def _lifespan(self, receive: Receive, send: Send) -> None:
        while True:
            message = await receive()
            if message["type"] == "lifespan.startup":
                try:
                    for hook in self._app._on_start:
                        await _call_hook(hook)
                except Exception as exc:
                    await send({"type": "lifespan.startup.failed", "message": str(exc)})
                    return
                await send({"type": "lifespan.startup.complete"})
            elif message["type"] == "lifespan.shutdown":
                try:
                    for hook in self._app._on_stop:
                        await _call_hook(hook)
                except Exception as exc:
                    await send({"type": "lifespan.shutdown.failed", "message": str(exc)})
                    return
                await send({"type": "lifespan.shutdown.complete"})
                return


def _build_url(scope: dict[str, Any]) -> URL:
    scheme = scope.get("scheme", "http")
    host: str | None = None
    for name, value in scope.get("headers", []):
        if name == b"host":
            host = value.decode("latin-1")
            break
    if not host:
        server = scope.get("server")
        if server:
            host = server[0]
            port = server[1]
            if port is not None and str(port) != _DEFAULT_SCHEME_PORTS.get(scheme):
                host = f"{host}:{port}"
        else:
            host = "localhost"
    raw_path = scope.get("raw_path")
    if raw_path:
        path = raw_path.decode("latin-1")
    else:
        path = quote(scope.get("path", "/"), safe=_PATH_SAFE)
    query = scope.get("query_string", b"").decode("latin-1")
    target = f"{scheme}://{host}{path}"
    if query:
        target += f"?{query}"
    return URL(target)


async def _send_response(scope: dict[str, Any], send: Send, response: Response) -> None:
    status = response.status
    body = response.body
    headers = [
        (name.encode("latin-1"), value.encode("latin-1")) for name, value in response.headers.raw()
    ]
    body_allowed = status >= 200 and status not in (204, 304)
    if body_allowed and not response.headers.has("content-length"):
        if isinstance(body, bytes):
            headers.append((b"content-length", str(len(body)).encode("latin-1")))
        elif body is None:
            headers.append((b"content-length", b"0"))
        # Stream bodies get no content-length; the server frames them.
    await send({"type": "http.response.start", "status": status, "headers": headers})
    suppress_body = scope["method"] == "HEAD" or not body_allowed
    if suppress_body or body is None:
        await send({"type": "http.response.body", "body": b"", "more_body": False})
        return
    if isinstance(body, bytes):
        await send({"type": "http.response.body", "body": body, "more_body": False})
        return
    async for chunk in body:
        await send({"type": "http.response.body", "body": bytes(chunk), "more_body": True})
    await send({"type": "http.response.body", "body": b"", "more_body": False})
