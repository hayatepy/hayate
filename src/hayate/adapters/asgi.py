"""ASGI adapter: translates ASGI ``http`` / ``lifespan`` events to ``app.fetch()``.

Users never see ``scope`` / ``receive`` / ``send`` — the ``Hayate`` app is
itself an ASGI callable that delegates here, so ``uvicorn main:app`` works
out of the box.
"""

from __future__ import annotations

import inspect
import logging
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import TYPE_CHECKING, Any
from urllib.parse import quote

from ..abort import AbortSignal
from ..context import Context
from ..headers import Headers
from ..request import HayateRequest, Request
from ..router import WEBSOCKET_METHOD
from ..url import URL
from ..websocket import WebSocket, WebSocketClosed

if TYPE_CHECKING:
    from ..app import Hayate
    from ..response import Response

_logger = logging.getLogger("hayate.asgi")

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
    """Translates ASGI events to ``app.fetch()``; ``Hayate`` instantiates it for you."""

    __slots__ = ("_app",)

    def __init__(self, app: Hayate) -> None:
        self._app = app

    async def __call__(self, scope: dict[str, Any], receive: Receive, send: Send) -> None:
        kind = scope["type"]
        if kind == "http":
            await self._http(scope, receive, send)
        elif kind == "websocket":
            await self._websocket(scope, receive, send)
        elif kind == "lifespan":
            await self._lifespan(receive, send)
        else:
            raise RuntimeError(f"unsupported ASGI scope type: {kind!r}")

    # -- http -----------------------------------------------------------------

    async def _http(self, scope: dict[str, Any], receive: Receive, send: Send) -> None:
        raw_headers: list[tuple[bytes, bytes]] = scope.get("headers", [])
        host: bytes | None = None
        expects_body = False
        for name, value in raw_headers:
            if name == b"host":
                if host is None:
                    host = value
            elif name == b"content-length":
                expects_body = value not in (b"", b"0")
            elif name == b"transfer-encoding":
                expects_body = True
        if expects_body:
            active_signal = AbortSignal()
            signal: AbortSignal | None = active_signal
            body: Any = _request_body(receive, active_signal)
        else:
            # No content-length / transfer-encoding means no request body
            # (RFC 9112) — a null body per Fetch; skip stream and signal.
            signal = None
            body = None
        request = Request(
            _build_url(scope, host),
            method=scope["method"],
            headers=Headers._from_wire(raw_headers, guard="immutable"),
            body=body,
            signal=signal,
        )
        response = await self._app.fetch(request)
        try:
            await _send_response(scope, send, response)
        finally:
            background = response._background
            if background is not None:
                await background._drain()

    # -- websocket ---------------------------------------------------------------

    async def _websocket(self, scope: dict[str, Any], receive: Receive, send: Send) -> None:
        raw_path = scope.get("raw_path")
        if raw_path:
            path = raw_path.decode("latin-1")
        else:
            path = quote(scope.get("path", "/"), safe=_PATH_SAFE)
        matched = self._app._router.match(WEBSOCKET_METHOD, path)
        if matched is None:
            await receive()  # websocket.connect
            await send({"type": "websocket.close", "code": 4404, "reason": "not found"})
            return
        route, params = matched
        raw_headers: list[tuple[bytes, bytes]] = scope.get("headers", [])
        host: bytes | None = None
        for name, value in raw_headers:
            if name == b"host":
                host = value
                break
        request = Request(
            _build_url(scope, host),
            headers=Headers._from_wire(raw_headers, guard="immutable"),
        )
        hayate_request = HayateRequest(request)
        hayate_request._params = params
        c = Context(hayate_request, self._app._env, None)
        ws = WebSocket(receive, send)
        await ws.accept()
        try:
            await route.handler(c, ws)
        except WebSocketClosed:
            pass
        except Exception:
            _logger.exception("websocket handler failed on %s", path)
            await ws.close(1011, "internal error")
            return
        await ws.close()

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


def _build_url(scope: dict[str, Any], host_header: bytes | None) -> URL:
    scheme = scope.get("scheme", "http")
    if host_header:
        host = host_header.decode("latin-1")
    else:
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
    return URL._from_server(scheme, host, path, query)


# Response header pairs repeat massively across requests (content-type,
# cache-control, ...), so their wire encoding is memoized: 114 ns -> 41 ns
# per pair (measured, DESIGN §14.4). Bounded so per-request values
# (set-cookie, etag) cannot grow it without bound — beyond the cap,
# uncached pairs are encoded directly.
_WIRE_CACHE: dict[tuple[str, str], tuple[bytes, bytes]] = {}
_WIRE_CACHE_MAX = 1024


def _wire_pair(pair: tuple[str, str]) -> tuple[bytes, bytes]:
    cached = _WIRE_CACHE.get(pair)
    if cached is None:
        cached = (pair[0].encode("latin-1"), pair[1].encode("latin-1"))
        if len(_WIRE_CACHE) < _WIRE_CACHE_MAX:
            _WIRE_CACHE[pair] = cached
    return cached


async def _send_response(scope: dict[str, Any], send: Send, response: Response) -> None:
    status = response.status
    body = response.body
    headers = [_wire_pair(pair) for pair in response.headers.raw()]
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
