"""ASGI adapter: translates ASGI ``http`` / ``lifespan`` events to ``app.fetch()``.

Users never see ``scope`` / ``receive`` / ``send`` — the ``Hayate`` app is
itself an ASGI callable that delegates here, so ``uvicorn main:app`` works
out of the box.
"""

from __future__ import annotations

import inspect
import logging
from collections.abc import Awaitable, Callable, Mapping
from typing import TYPE_CHECKING, Any, cast
from urllib.parse import quote

from ..abort import AbortSignal
from ..context import Context
from ..headers import Headers
from ..request import HayateRequest, Request
from ..router import WEBSOCKET_METHOD
from ..url import URL, _needs_dot_removal, _remove_dot_segments
from ..websocket import WebSocket, WebSocketClosed

if TYPE_CHECKING:
    from ..app import Hayate
    from ..response import Response

_logger = logging.getLogger("hayate.asgi")

type Receive = Callable[[], Awaitable[dict[str, Any]]]
type Send = Callable[[dict[str, Any]], Awaitable[None]]
type ASGIApplication = Callable[[dict[str, Any], Receive, Send], Awaitable[None]]

_DEFAULT_SCHEME_PORTS = {"http": "80", "https": "443", "ws": "80", "wss": "443"}
# pchar set — keep valid path characters intact when re-encoding a decoded path.
_PATH_SAFE = "/:@!$&'()*+,;=~-._"
_MOUNT_PATH_CHARS = frozenset(
    "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-._~!$&'()*+,;=:@/"
)


def _validate_mount_path(path: str) -> bytes:
    if not path.startswith("/") or path == "/":
        raise ValueError("ASGI mount paths must start with '/' and cannot be '/'")
    if path.endswith("/"):
        raise ValueError("ASGI mount paths must not end with '/'")
    if any(segment in ("", ".", "..") for segment in path[1:].split("/")):
        raise ValueError("ASGI mount paths cannot contain empty, '.' or '..' segments")
    if any(character not in _MOUNT_PATH_CHARS for character in path):
        raise ValueError("ASGI mount paths must contain only unescaped ASCII URL path characters")
    return path.encode("ascii")


def _mounted_scope(
    scope: dict[str, Any],
    *,
    path: str,
    prefix: str,
    raw_prefix: bytes,
) -> dict[str, Any]:
    mounted = dict(scope)
    mounted["path"] = path[len(prefix) :] or "/"

    root_path = str(scope.get("root_path", "")).rstrip("/")
    mounted["root_path"] = f"{root_path}{prefix}"

    raw_path = scope.get("raw_path")
    if isinstance(raw_path, bytes) and (
        raw_path == raw_prefix or raw_path.startswith(raw_prefix + b"/")
    ):
        mounted["raw_path"] = raw_path[len(raw_prefix) :] or b"/"
    else:
        # ``raw_path`` is optional in ASGI. If an upstream server encoded the
        # mount prefix differently, dropping it is safer than fabricating raw
        # bytes that no longer describe ``path``.
        mounted.pop("raw_path", None)
    return mounted


class ASGIPathDispatcher:
    """Dispatch mounted ASGI applications before a default application.

    HTTP and WebSocket scopes use longest path-segment prefix matching.
    Mounted applications receive the remaining ``path`` and ``raw_path`` plus
    a ``root_path`` extended by the matched prefix. Other scopes, including
    lifespan, are owned by ``default``. The composition root must initialize
    and shut down mounted applications that require their own lifecycle.

    This adapter-level boundary is intentionally separate from Hayate's Fetch
    core and its direct Cloudflare Workers adapter.
    """

    __slots__ = ("_default", "_mounts")

    def __init__(
        self,
        default: ASGIApplication,
        mounts: Mapping[str, ASGIApplication],
    ) -> None:
        if not callable(default):
            raise TypeError("default ASGI application must be callable")

        prepared: list[tuple[str, bytes, ASGIApplication]] = []
        for path, application in mounts.items():
            raw_path = _validate_mount_path(path)
            if not callable(application):
                raise TypeError(f"mounted ASGI application at {path!r} must be callable")
            prepared.append((path, raw_path, application))

        self._default = default
        self._mounts = tuple(sorted(prepared, key=lambda mount: (-len(mount[0]), mount[0])))

    async def __call__(
        self,
        scope: dict[str, Any],
        receive: Receive,
        send: Send,
    ) -> None:
        if scope.get("type") not in ("http", "websocket"):
            await self._default(scope, receive, send)
            return

        path = str(scope.get("path", "/"))
        for prefix, raw_prefix, application in self._mounts:
            if path == prefix or path.startswith(f"{prefix}/"):
                await application(
                    _mounted_scope(
                        scope,
                        path=path,
                        prefix=prefix,
                        raw_prefix=raw_prefix,
                    ),
                    receive,
                    send,
                )
                return
        await self._default(scope, receive, send)


class _ASGIRequestBody:
    """One-shot ASGI receive channel exposed as a Fetch body.

    A concrete async iterator avoids creating an async-generator object and
    registering its event-loop finalizer for every request with a body.
    Buffered readers use the same receive channel directly; applications that
    iterate ``request.body`` still observe each non-empty ASGI chunk.
    """

    __slots__ = ("_done", "_receive", "_signal")

    def __init__(self, receive: Receive, signal: AbortSignal) -> None:
        self._receive = receive
        self._signal = signal
        self._done = False

    def __aiter__(self) -> _ASGIRequestBody:
        return self

    async def __anext__(self) -> bytes:
        while not self._done:
            message = await self._receive()
            if message["type"] == "http.request":
                chunk = bytes(message.get("body", b""))
                if not message.get("more_body", False):
                    self._done = True
                if chunk:
                    return chunk
            elif message["type"] == "http.disconnect":
                self._done = True
                self._signal._abort("client disconnected")
        raise StopAsyncIteration

    async def bytes(self) -> bytes:
        first = await anext(self, None)
        if first is None:
            return b""
        second = await anext(self, None)
        if second is None:
            return bytes(first)
        chunks = [bytes(first), bytes(second)]
        async for chunk in self:
            chunks.append(bytes(chunk))
        return b"".join(chunks)

    async def text(self) -> str:
        return (await self.bytes()).decode("utf-8", errors="replace")


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
            platform_body: _ASGIRequestBody | None = _ASGIRequestBody(receive, active_signal)
        else:
            # No content-length / transfer-encoding means no request body
            # (RFC 9112) — a null body per Fetch; skip stream and signal.
            signal = None
            platform_body = None
        routing_path = _routing_path(scope)
        request = Request(
            "",
            method=scope["method"].upper(),
            headers=Headers._from_wire(raw_headers, guard="immutable"),
            signal=signal,
            _trusted_pathname=routing_path,
        )
        request._init_platform_url((scope, host, routing_path), _load_asgi_url)
        if platform_body is not None:
            request._init_platform_body(platform_body)
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
        routing_path = _routing_path(scope)
        request = Request(
            "",
            headers=Headers._from_wire(raw_headers, guard="immutable"),
            _trusted_pathname=routing_path,
        )
        request._init_platform_url((scope, host, routing_path), _load_asgi_url)
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


def _routing_path(scope: dict[str, Any]) -> str:
    """Return the canonical pathname needed by the router.

    The remaining scheme, authority, and query components stay in the ASGI
    scope and are decoded only when application code observes ``c.req.url``.
    """
    raw_path = scope.get("raw_path")
    if raw_path:
        path = raw_path.decode("latin-1")
    else:
        path = quote(scope.get("path", "/"), safe=_PATH_SAFE)
    if not path:
        path = "/"
    elif _needs_dot_removal(path):
        path = _remove_dot_segments(path)
    return cast(str, path)


def _load_asgi_url(source: Any) -> URL:
    """Materialize a trusted ASGI request URL on first application access."""
    scope, host_header, path = source
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
    pairs = response._header_pairs_for_adapter()
    headers = [_wire_pair(pair) for pair in pairs]
    body_allowed = status >= 200 and status not in (204, 304)
    # Trusted Context response helpers keep their default header pairs outside
    # a mutable Headers object, and those pairs never contain content-length.
    # Avoid allocating/scanning a generator on the overwhelmingly common path.
    has_content_length = response._headers is not None and any(
        name == "content-length" for name, _ in pairs
    )
    if body_allowed and not has_content_length:
        if isinstance(body, bytes):
            headers.append(_wire_pair(("content-length", str(len(body)))))
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
