"""Cloudflare Python Workers adapter.

Usage — the entry module of a Python Worker:

    from hayate.adapters.workers import to_workers
    from app import app

    Default = to_workers(app)

A Durable Object mounts an app the same way Hono does — build it in the
constructor so route closures capture the object's state. The factory's
name becomes the exported class name (must match ``class_name`` in
wrangler.toml):

    from hayate.adapters.workers import to_durable_object

    @to_durable_object
    def Counter(ctx, env):
        app = Hayate()

        @app.get("/count")
        async def count(c):
            n = int((await ctx.storage.get("n")) or 0) + 1
            await ctx.storage.put("n", n)
            return c.json({"count": n})

        return app

The Workers runtime modules (``workers``, ``js``) exist only inside
Pyodide, so they are imported when the entrypoint class is built; the
translation helpers are plain Python and unit-testable anywhere.

Unlike the official FastAPI integration (JS Request -> ASGI -> Starlette
Request), this is a single-step translation: JS Request -> hayate
Request, same conceptual model on both sides.

Bodies stream across the FFI boundary when the runtime provides the
pieces: a JS ``ReadableStream`` request body is surfaced to the app as an
``AsyncIterable[bytes]``, and an async-iterable response body becomes a
JS ``ReadableStream`` via ``ReadableStream.from()``. Anything else falls
back to the buffered crossing. The JS ``AbortSignal`` is mirrored onto
``request.signal``. ``@app.ws()`` routes are served through
``WebSocketPair`` — an ``Upgrade: websocket`` request matching a
websocket route returns ``101`` with the client socket, and the handler
drives the server socket through the same ``WebSocket`` API as on ASGI.

Every ``create_proxy`` made for a request (abort listener, response
generator, websocket listeners) is destroyed deterministically when that
request's lifecycle ends — engines do not guarantee FinalizationRegistry
callbacks, so garbage collection is a backstop, not the mechanism.
On-workerd verification is tracked in docs/research/cloudflare.md §5.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import AsyncIterable, AsyncIterator, Callable
from typing import TYPE_CHECKING, Any

from ..abort import AbortSignal
from ..context import Context, ExecutionContext
from ..headers import Headers
from ..request import HayateRequest, Request
from ..response import Response
from ..router import WEBSOCKET_METHOD
from ..url import URL
from ..websocket import WebSocket, WebSocketClosed

if TYPE_CHECKING:
    from ..app import Hayate

_logger = logging.getLogger("hayate.workers")

try:  # Pyodide-only; under CPython (tests) the helpers run without them.
    from pyodide.ffi import create_proxy as _create_proxy
    from pyodide.ffi import to_js as _to_js
except ImportError:
    _create_proxy = None
    _to_js = None

# The event loop only holds tasks weakly; websocket handlers outlive the
# fetch that spawned them, so keep strong references until each ends.
_live_connections: set[asyncio.Task[None]] = set()


class _Runtime:
    """Handles to the Workers runtime pieces, resolved once per entrypoint."""

    __slots__ = ("headers_cls", "readable_stream_cls", "response_cls", "websocket_pair_cls")

    def __init__(self) -> None:
        from js import Headers as headers_cls
        from workers import Response as response_cls

        self.headers_cls = headers_cls
        self.response_cls = response_cls
        try:
            from js import ReadableStream as readable_stream_cls
        except ImportError:  # a runtime without streams: responses are buffered
            readable_stream_cls = None
        self.readable_stream_cls = readable_stream_cls
        try:
            from js import WebSocketPair as websocket_pair_cls
        except ImportError:  # a runtime without WebSocketPair: no upgrades
            websocket_pair_cls = None
        self.websocket_pair_cls = websocket_pair_cls


def _proxy(obj: Any) -> Any:
    return obj if _create_proxy is None else _create_proxy(obj)


def _destroy(proxy: Any) -> None:
    if _create_proxy is not None:
        proxy.destroy()


def _once(*callbacks: Callable[[], None] | None) -> Callable[[], None]:
    """Combine cleanups into one idempotent, never-raising callable."""
    pending = [callback for callback in callbacks if callback is not None]

    def run() -> None:
        while pending:
            with contextlib.suppress(Exception):
                pending.pop()()

    return run


_MISSING = object()


def _js_headers_to_pairs(js_headers: Any) -> list[tuple[str, str]]:
    # Raw JS Headers proxies iterate via entries(); the workers-py Python
    # wrapper is a Mapping with items(). Support both shapes.
    entries = getattr(js_headers, "entries", None)
    if entries is not None:
        return [(str(entry[0]), str(entry[1])) for entry in entries()]
    return [(str(name), str(value)) for name, value in js_headers.items()]


def _url_from_trusted(href: str) -> URL:
    """Split a platform-validated absolute URL without re-validation.

    The runtime hands the adapter an already-parsed, re-serialized
    request URL, so the full WHATWG parse (validation, percent-encoding
    probes) would only redo its work — the component split is ~10x
    cheaper (measured). Anything surprising falls back to the parser.
    """
    scheme, sep, rest = href.partition("://")
    if not sep or not scheme or "#" in rest:
        return URL(href)  # not a served request URL; take the strict path
    authority, slash, path_query = rest.partition("/")
    if "@" in authority or not authority:
        return URL(href)  # userinfo never appears in served URLs
    path, _, query = path_query.partition("?")
    return URL._from_server(scheme, authority, slash + path if slash else "/", query)


def _probe(js_request: Any, name: str) -> Any:
    """Read a Fetch property from either runtime shape.

    Raw JS proxies carry Fetch properties themselves; the workers-py
    wrapper forwards some (``body``) and keeps others only on the raw
    JS request it holds as ``js_object`` (``signal``).
    """
    value = getattr(js_request, name, None)
    if value is not None:
        return value
    js_object = getattr(js_request, "js_object", None)
    return None if js_object is None else getattr(js_object, name, None)


def _body_source(js_request: Any) -> Any:
    """The request's body: None (null body), a value, or ``_MISSING``.

    Distinguishing "the shape exposes ``body`` and it is null" from "the
    shape has no ``body`` at all" lets bodyless requests skip the
    buffered FFI read entirely — per Fetch, a null ``body`` *is* the
    statement that there is nothing to read.
    """
    value = getattr(js_request, "body", _MISSING)
    if value is _MISSING or value is None:
        js_object = getattr(js_request, "js_object", None)
        if js_object is not None:
            inner = getattr(js_object, "body", _MISSING)
            if inner is not _MISSING:
                return inner
    return value


def _js_bytes(value: Any) -> bytes:
    """Bytes from a JS binary value (ArrayBuffer or view) or Python buffer.

    ``to_py()`` converts TypedArray views but passes a bare ArrayBuffer
    through unchanged (observed on workerd: websocket ``event.data``), so
    prefer the JsBuffer API, which covers both.
    """
    to_bytes = getattr(value, "to_bytes", None)
    if to_bytes is not None:
        return to_bytes()
    if hasattr(value, "to_py"):
        value = value.to_py()
    return bytes(value)


async def _iter_js_stream(js_stream: Any) -> AsyncIterator[bytes]:
    """Drive a JS ReadableStream reader as an async byte iterator."""
    reader = js_stream.getReader()
    while True:
        result = await reader.read()
        if result.done:
            return
        yield _js_bytes(result.value)


async def _read_body(js_request: Any) -> bytes | None:
    """Read the whole request body: the buffered crossing.

    On workerd the handler receives workers-py's Python Request wrapper
    (reader: ``await request.bytes()``), not a raw JS proxy (reader:
    ``await request.arrayBuffer()``) — verified on workerd, 2026-07.
    Reading unconditionally is safe: bodyless requests yield b"".
    """
    reader = getattr(js_request, "arrayBuffer", None)
    if reader is None:
        reader = getattr(js_request, "bytes", None)
    if reader is None:
        return None
    return _js_bytes(await reader()) or None


def _bridge_abort_signal(js_request: Any) -> tuple[AbortSignal | None, Callable[[], None] | None]:
    """Mirror the JS AbortSignal, returning the signal and its release."""
    js_signal = _probe(js_request, "signal")
    if js_signal is None or not hasattr(js_signal, "addEventListener"):
        return None, None
    signal = AbortSignal()

    def on_abort(*_event: Any) -> None:
        signal._abort(getattr(js_signal, "reason", None))

    # An implicitly-converted callable would be destroyed when this call
    # returns (the classic addEventListener trap) — create_proxy keeps the
    # listener alive until the release below destroys it.
    listener = _proxy(on_abort)
    js_signal.addEventListener("abort", listener)
    if getattr(js_signal, "aborted", False):
        on_abort()  # aborted before the listener was attached

    def release() -> None:
        js_signal.removeEventListener("abort", listener)
        _destroy(listener)

    return signal, release


async def _to_hayate_request(js_request: Any) -> tuple[Request, Callable[[], None] | None]:
    source = _body_source(js_request)
    if source is None:
        body: Any = None  # Fetch null body: nothing to read, skip the crossing
    elif source is not _MISSING and hasattr(source, "getReader"):
        body = _iter_js_stream(source)
    else:
        body = await _read_body(js_request)
    signal, release = _bridge_abort_signal(js_request)
    request = Request(
        _url_from_trusted(str(js_request.url)),
        method=str(js_request.method),
        headers=Headers._from_trusted_pairs(
            _js_headers_to_pairs(js_request.headers), guard="immutable"
        ),
        body=body,
        signal=signal,
    )
    return request, release


def _js_stream_from_body(
    body: AsyncIterable[bytes], readable_stream_cls: Any, on_done: Callable[[], None]
) -> Any:
    """Build a JS ReadableStream from an async byte iterable, or None.

    ``ReadableStream.from(asyncIterable)`` (unconditional in workerd)
    consumes the async-iteration protocol of the generator's proxy;
    chunks cross pre-converted to ``Uint8Array``. ``on_done`` runs when
    the stream finishes or is canceled, and the generator's own proxy is
    destroyed one tick later — after its final result crossed to JS.
    """
    stream_from = getattr(readable_stream_cls, "from", None) if readable_stream_cls else None
    if stream_from is None:
        return None

    proxy_ref: list[Any] = []

    async def chunks() -> AsyncIterator[Any]:
        try:
            async for chunk in body:
                data = bytes(chunk)
                yield data if _to_js is None else _to_js(data)
        finally:
            on_done()
            if proxy_ref:
                asyncio.get_running_loop().call_soon(proxy_ref.pop().destroy)

    generator = chunks()
    if _create_proxy is None:
        handle: Any = generator
    else:
        handle = _create_proxy(generator)
        proxy_ref.append(handle)
    try:
        return stream_from(handle)
    except Exception:
        if proxy_ref:  # the generator has not started; buffering stays correct
            proxy_ref.pop().destroy()
        return None


# Statuses whose responses must not carry a body (Fetch "null body status").
_NULL_BODY_STATUSES = frozenset((101, 103, 204, 205, 304))


async def _to_workers_response(
    response: Response, runtime: _Runtime, on_done: Callable[[], None]
) -> Any:
    platform_response = getattr(response, "platform_response", None)
    if platform_response is not None:  # forward(): return it untouched
        on_done()
        return platform_response
    # One crossing for the whole header list — the JS Headers constructor
    # takes a sequence of pairs, so per-header append() calls (N proxy
    # round-trips) are unnecessary.
    pairs = response.headers.raw()
    js_headers = runtime.headers_cls.new(pairs if _to_js is None else _to_js(pairs))
    body = None if response.status in _NULL_BODY_STATUSES else response.body
    if body is not None and not isinstance(body, bytes):
        stream = _js_stream_from_body(body, runtime.readable_stream_cls, on_done)
        if stream is not None:
            # workers.Response accepts a ReadableStream body (it is in the
            # SDK's RESPONSE_ACCEPTED_TYPES); an SDK that rejects it falls
            # back to buffering — the generator has not started yet, so
            # canceling the stream releases its proxy without touching
            # the underlying body iterable.
            try:
                return runtime.response_cls(stream, status=response.status, headers=js_headers)
            except Exception:
                with contextlib.suppress(Exception):
                    stream.cancel()
        body = await response.bytes()
    on_done()
    return runtime.response_cls(body, status=response.status, headers=js_headers)


class _WorkersExecutionContext(ExecutionContext):
    """Forwards ``wait_until`` to the Workers runtime (``ctx.waitUntil``).

    Also carries the original platform request so ``forward()`` can hand
    it to a Fetcher binding untouched.
    """

    __slots__ = ("_js_ctx", "js_request")

    def __init__(self, js_ctx: Any, js_request: Any = None) -> None:
        super().__init__()
        self._js_ctx = js_ctx
        self.js_request = js_request

    def wait_until(self, awaitable: Any) -> None:
        # Pyodide converts asyncio futures to JS promises at the boundary.
        self._js_ctx.waitUntil(asyncio.ensure_future(awaitable))


class _PassthroughResponse(Response):
    """A platform response that must cross the boundary untouched."""

    __slots__ = ("platform_response",)


async def forward(c: Context, fetcher: Any) -> Response:
    """Forward the original platform request to a Fetcher binding.

    ``fetcher`` is anything with a Workers ``fetch`` — a Durable Object
    stub (``c.env.NS.getByName(name)``) or a service binding. The
    response crosses back *untouched*, so platform extensions survive:
    an accepted websocket upgrade (the ``webSocket`` property of a
    ``101``) reaches the client even through this app, which a rebuilt
    ``Response`` cannot carry. Because it is exactly the platform's
    response, staged response middleware mutations (``c.header()``) do
    not apply to it.
    """
    js_request = getattr(c._exec, "js_request", None)
    if js_request is None:
        raise RuntimeError(
            "forward() needs the original platform request; it is only "
            "available under the Workers adapter (to_workers / to_durable_object)"
        )
    raw = getattr(js_request, "js_object", None)
    js_response = await fetcher.fetch(raw if raw is not None else js_request)
    response = _PassthroughResponse(None, int(getattr(js_response, "status", None) or 200))
    response.platform_response = js_response
    return response


def _accept_websocket(
    route: Any,
    params: dict[str, str | None],
    request: Request,
    env: Any,
    js_ctx: Any,
    runtime: _Runtime,
    release: Callable[[], None],
) -> Any:
    """Upgrade via WebSocketPair and drive the handler over the server side.

    The handler sees the exact ``WebSocket`` surface it sees on ASGI: the
    JS events are queued as ASGI-shaped messages, and sends map onto the
    server socket. Returns the ``101`` response holding the client side.
    """
    client, server = runtime.websocket_pair_cls.new().object_values()
    server.accept()
    # Binary frames arrive as Blob by default, which only offers async
    # readers; ArrayBuffer keeps the message listener synchronous
    # (WHATWG WebSocket ``binaryType``). Observed on workerd, 2026-07.
    server.binaryType = "arraybuffer"

    queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
    queue.put_nowait({"type": "websocket.connect"})

    def on_message(event: Any) -> None:
        data = event.data
        if isinstance(data, str):
            queue.put_nowait({"type": "websocket.receive", "text": data})
        else:
            queue.put_nowait({"type": "websocket.receive", "bytes": _js_bytes(data)})

    def on_close(event: Any) -> None:
        queue.put_nowait(
            {
                "type": "websocket.disconnect",
                "code": getattr(event, "code", None) or 1005,
                "reason": getattr(event, "reason", None) or "",
            }
        )

    def on_error(_event: Any) -> None:
        queue.put_nowait({"type": "websocket.disconnect", "code": 1006, "reason": "error"})

    listeners = [
        ("message", _proxy(on_message)),
        ("close", _proxy(on_close)),
        ("error", _proxy(on_error)),
    ]
    for event_name, listener in listeners:
        server.addEventListener(event_name, listener)

    async def receive() -> dict[str, Any]:
        return await queue.get()

    async def send(message: dict[str, Any]) -> None:
        kind = message["type"]
        if kind == "websocket.send":
            text = message.get("text")
            if text is not None:
                server.send(text)
            else:
                data = message.get("bytes", b"")
                server.send(data if _to_js is None else _to_js(data))
        elif kind == "websocket.close":
            # Best-effort: the peer may already be gone.
            with contextlib.suppress(Exception):
                server.close(message.get("code", 1000), message.get("reason", ""))
        # "websocket.accept" needs no action: the pair was accepted above.

    ws = WebSocket(receive, send)
    hayate_request = HayateRequest(request)
    hayate_request._params = params
    c = Context(hayate_request, env, _WorkersExecutionContext(js_ctx))

    async def run() -> None:
        try:
            await ws.accept()  # consumes the synthetic connect message
            try:
                await route.handler(c, ws)
            except WebSocketClosed:
                pass
            except Exception:
                _logger.exception("websocket handler failed on %s", request.url.pathname)
                await ws.close(1011, "internal error")
                return
            await ws.close()
        finally:
            for event_name, listener in listeners:
                with contextlib.suppress(Exception):
                    server.removeEventListener(event_name, listener)
                _destroy(listener)
            release()

    task = asyncio.ensure_future(run())
    _live_connections.add(task)
    task.add_done_callback(_live_connections.discard)
    return runtime.response_cls(None, status=101, web_socket=client)


async def _handle_fetch(
    app: Hayate, js_request: Any, js_ctx: Any, env: Any, runtime: _Runtime
) -> Any:
    request, release_signal = await _to_hayate_request(js_request)
    release = _once(release_signal)
    try:
        if runtime.websocket_pair_cls is not None:
            upgrade = request.headers.get("upgrade")
            if upgrade is not None and upgrade.lower() == "websocket":
                matched = app._router.match(WEBSOCKET_METHOD, request.url.pathname)
                if matched is not None:
                    route, params = matched
                    return _accept_websocket(route, params, request, env, js_ctx, runtime, release)
        exec_ctx = _WorkersExecutionContext(js_ctx, js_request)
        response = await app.fetch(request, env=env, ctx=exec_ctx)
        return await _to_workers_response(response, runtime, on_done=release)
    except BaseException:  # adapter failure or cancellation: do not leak the proxy
        release()
        raise


def to_workers(app: Hayate) -> type:
    """Build the Workers entrypoint class: ``Default = to_workers(app)``."""
    from workers import WorkerEntrypoint

    runtime = _Runtime()

    class Default(WorkerEntrypoint):
        async def fetch(self, request: Any) -> Any:
            return await _handle_fetch(app, request, self.ctx, self.env, runtime)

    return Default


def to_durable_object(factory: Callable[[Any, Any], Hayate]) -> type:
    """Build a Durable Object class that serves a hayate app from ``fetch``.

    ``factory(ctx, env)`` runs once per object instance and returns the
    app; route closures capture ``ctx.storage`` (the same idiom Hono
    uses — build the app in the constructor). Websocket routes work here
    too: a direct upgrade request to the object returns ``101``.

    The runtime registers Durable Object classes by ``__name__`` (workerd
    ``introspection.py``), so the factory's name becomes the class name
    and must match ``class_name`` in wrangler.toml — most natural as a
    decorator::

        @to_durable_object
        def Counter(ctx, env):
            app = Hayate()
            ...
            return app
    """
    from workers import DurableObject

    runtime = _Runtime()

    class HayateDurableObject(DurableObject):
        def __init__(self, ctx: Any, env: Any) -> None:
            super().__init__(ctx, env)
            self._app = factory(ctx, env)

        async def fetch(self, request: Any) -> Any:
            return await _handle_fetch(self._app, request, self.ctx, self.env, runtime)

    HayateDurableObject.__name__ = factory.__name__
    HayateDurableObject.__qualname__ = factory.__name__
    return HayateDurableObject
