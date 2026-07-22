"""Cloudflare Python Workers adapter.

Usage — the entry module of a Python Worker:

    from hayate.adapters.workers import to_workers
    from app import app

    Default = to_workers(app)

The Workers runtime modules (``workers``, ``js``) exist only inside
Pyodide, so they are imported inside ``to_workers()``; the translation
helpers are plain Python and unit-testable anywhere.

Unlike the official FastAPI integration (JS Request -> ASGI -> Starlette
Request), this is a single-step translation: JS Request -> hayate
Request, same conceptual model on both sides.

Bodies stream across the FFI boundary when the runtime provides the
pieces: a JS ``ReadableStream`` request body is surfaced to the app as an
``AsyncIterable[bytes]``, and an async-iterable response body becomes a
JS ``ReadableStream`` via ``ReadableStream.from()``. Anything else falls
back to the buffered crossing. The JS ``AbortSignal`` is mirrored onto
``request.signal``. On-workerd verification of the streaming paths is
tracked in docs/research/cloudflare.md §5.
"""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import AsyncIterable, AsyncIterator
from typing import TYPE_CHECKING, Any

from ..abort import AbortSignal
from ..context import ExecutionContext
from ..headers import Headers
from ..request import Request

if TYPE_CHECKING:
    from ..app import Hayate
    from ..response import Response

try:  # Pyodide-only; under CPython (tests) the helpers run without them.
    from pyodide.ffi import create_proxy as _create_proxy
    from pyodide.ffi import to_js as _to_js
except ImportError:
    _create_proxy = None
    _to_js = None


def _js_headers_to_pairs(js_headers: Any) -> list[tuple[str, str]]:
    # Raw JS Headers proxies iterate via entries(); the workers-py Python
    # wrapper is a Mapping with items(). Support both shapes.
    entries = getattr(js_headers, "entries", None)
    if entries is not None:
        return [(str(entry[0]), str(entry[1])) for entry in entries()]
    return [(str(name), str(value)) for name, value in js_headers.items()]


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


def _js_body_stream(js_request: Any) -> Any:
    """The request's JS ReadableStream, or None to fall back to buffering."""
    body = _probe(js_request, "body")
    return body if body is not None and hasattr(body, "getReader") else None


async def _iter_js_stream(js_stream: Any) -> AsyncIterator[bytes]:
    """Drive a JS ReadableStream reader as an async byte iterator."""
    reader = js_stream.getReader()
    while True:
        result = await reader.read()
        if result.done:
            return
        value = result.value
        if hasattr(value, "to_py"):
            value = value.to_py()
        yield bytes(value)


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
    data = await reader()
    if hasattr(data, "to_py"):
        data = data.to_py()
    return bytes(data) or None


def _bridge_abort_signal(js_request: Any) -> AbortSignal | None:
    """Mirror the JS AbortSignal onto a hayate AbortSignal, if present."""
    js_signal = _probe(js_request, "signal")
    if js_signal is None or not hasattr(js_signal, "addEventListener"):
        return None
    signal = AbortSignal()

    def on_abort(*_event: Any) -> None:
        signal._abort(getattr(js_signal, "reason", None))

    # An implicitly-converted callable would be destroyed when this call
    # returns (the classic addEventListener trap) — create_proxy keeps the
    # listener alive for the lifetime of the request.
    listener = on_abort if _create_proxy is None else _create_proxy(on_abort)
    js_signal.addEventListener("abort", listener)
    if getattr(js_signal, "aborted", False):
        on_abort()  # aborted before the listener was attached
    return signal


async def _to_hayate_request(js_request: Any) -> Request:
    stream = _js_body_stream(js_request)
    body = _iter_js_stream(stream) if stream is not None else await _read_body(js_request)
    return Request(
        str(js_request.url),
        method=str(js_request.method),
        headers=Headers(_js_headers_to_pairs(js_request.headers), guard="immutable"),
        body=body,
        signal=_bridge_abort_signal(js_request),
    )


def _js_stream_from_body(body: AsyncIterable[bytes], readable_stream_cls: Any) -> Any:
    """Build a JS ReadableStream from an async byte iterable, or None.

    ``ReadableStream.from(asyncIterable)`` (unconditional in workerd)
    consumes the async-iteration protocol of the generator's proxy;
    chunks cross pre-converted to ``Uint8Array``.
    """
    stream_from = getattr(readable_stream_cls, "from", None)
    if stream_from is None:
        return None

    async def chunks() -> AsyncIterator[Any]:
        async for chunk in body:
            data = bytes(chunk)
            yield data if _to_js is None else _to_js(data)

    generator = chunks()
    try:
        return stream_from(generator if _create_proxy is None else _create_proxy(generator))
    except Exception:
        return None  # the generator has not started; buffering stays correct


async def _to_workers_response(
    response: Response,
    workers_response_cls: Any,
    js_headers_cls: Any,
    readable_stream_cls: Any = None,
) -> Any:
    js_headers = js_headers_cls.new()
    for name, value in response.headers.raw():
        js_headers.append(name, value)
    body = response.body
    if body is not None and not isinstance(body, bytes):
        stream = _js_stream_from_body(body, readable_stream_cls)
        if stream is not None:
            # workers.Response accepts a ReadableStream body (it is in the
            # SDK's RESPONSE_ACCEPTED_TYPES); an SDK that rejects it falls
            # back to buffering — the generator has not started yet.
            with contextlib.suppress(Exception):
                return workers_response_cls(stream, status=response.status, headers=js_headers)
        body = await response.bytes()
    return workers_response_cls(body, status=response.status, headers=js_headers)


class _WorkersExecutionContext(ExecutionContext):
    """Forwards ``wait_until`` to the Workers runtime (``ctx.waitUntil``)."""

    __slots__ = ("_js_ctx",)

    def __init__(self, js_ctx: Any) -> None:
        super().__init__()
        self._js_ctx = js_ctx

    def wait_until(self, awaitable: Any) -> None:
        # Pyodide converts asyncio futures to JS promises at the boundary.
        self._js_ctx.waitUntil(asyncio.ensure_future(awaitable))


def to_workers(app: Hayate) -> type:
    """Build the Workers entrypoint class: ``Default = to_workers(app)``."""
    from js import Headers as JsHeaders
    from workers import Response as WorkersResponse
    from workers import WorkerEntrypoint

    try:
        from js import ReadableStream as JsReadableStream
    except ImportError:  # a runtime without streams: responses are buffered
        JsReadableStream = None

    class Default(WorkerEntrypoint):
        async def fetch(self, request: Any) -> Any:
            hayate_request = await _to_hayate_request(request)
            exec_ctx = _WorkersExecutionContext(self.ctx)
            response = await app.fetch(hayate_request, env=self.env, ctx=exec_ctx)
            return await _to_workers_response(
                response, WorkersResponse, JsHeaders, JsReadableStream
            )

    return Default
