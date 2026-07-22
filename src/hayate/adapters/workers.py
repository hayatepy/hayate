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

v0.2 scope: bodies are buffered across the FFI boundary (streaming
bridges need on-platform verification — docs/research/cloudflare.md §5)
and the abort signal is not yet bridged.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any

from ..context import ExecutionContext
from ..headers import Headers
from ..request import Request

if TYPE_CHECKING:
    from ..app import Hayate
    from ..response import Response


def _js_headers_to_pairs(js_headers: Any) -> list[tuple[str, str]]:
    return [(str(entry[0]), str(entry[1])) for entry in js_headers.entries()]


async def _to_hayate_request(js_request: Any) -> Request:
    body: bytes | None = None
    if js_request.body is not None:
        buffer = await js_request.arrayBuffer()
        data = buffer.to_py() if hasattr(buffer, "to_py") else buffer
        body = bytes(data) or None
    return Request(
        str(js_request.url),
        method=str(js_request.method),
        headers=Headers(_js_headers_to_pairs(js_request.headers), guard="immutable"),
        body=body,
    )


async def _to_workers_response(
    response: Response, workers_response_cls: Any, js_headers_cls: Any
) -> Any:
    body = response.body
    if body is not None and not isinstance(body, bytes):
        body = await response.bytes()  # buffered crossing in v0.2
    js_headers = js_headers_cls.new()
    for name, value in response.headers.raw():
        js_headers.append(name, value)
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

    class Default(WorkerEntrypoint):
        async def fetch(self, request: Any) -> Any:
            hayate_request = await _to_hayate_request(request)
            exec_ctx = _WorkersExecutionContext(self.ctx)
            response = await app.fetch(hayate_request, env=self.env, ctx=exec_ctx)
            return await _to_workers_response(response, WorkersResponse, JsHeaders)

    return Default
