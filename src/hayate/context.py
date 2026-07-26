"""Request context: the single object handlers and middleware receive."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterable, Awaitable, Callable, Iterable, Mapping
from typing import Any

from .body import BodyInit
from .cookies import serialize_set_cookie
from .exceptions import problem
from .headers import Headers
from .jsonutil import dumps_compact
from .request import HayateRequest
from .response import Response
from .sse import SSEMessage, event_stream

type Next = Callable[[], Awaitable[None]]
type HeadersArg = Headers | Mapping[str, str] | Iterable[tuple[str, str]] | None
type Handler = Callable[["Context"], Awaitable[Response | None] | Response | None]
type Middleware = Callable[["Context", Next], Awaitable[Response | None]]
type ErrorHandler = Callable[[Exception, "Context"], Awaitable[Response]]

_logger = logging.getLogger("hayate")


class ExecutionContext:
    """Deferred work that must complete after the response is sent.

    Mirrors the Workers ``ExecutionContext``: ``wait_until()`` schedules an
    awaitable, and the active adapter drains the scheduled work after the
    response has been delivered. When ``app.fetch()`` is called without an
    explicit context (tests, embedding), it drains before returning.
    """

    __slots__ = ("_tasks",)

    def __init__(self) -> None:
        self._tasks: list[asyncio.Future[Any]] = []

    def wait_until(self, awaitable: Awaitable[Any]) -> None:
        self._tasks.append(asyncio.ensure_future(awaitable))

    async def _drain(self) -> None:
        tasks, self._tasks = self._tasks, []
        for task in tasks:
            try:
                await task
            except Exception:
                _logger.exception("background task scheduled via wait_until() failed")


class Context:
    """The one object handlers and middleware receive: request, env, and response helpers."""

    __slots__ = (
        "_exec",
        "_exec_arg1",
        "_exec_arg2",
        "_exec_factory",
        "_external_exec",
        "_header_ops",
        "_res",
        "_vars",
        "env",
        "req",
    )

    def __init__(self, req: HayateRequest, env: Any, exec_ctx: ExecutionContext | None) -> None:
        self.req = req
        self.env = env
        self._exec = exec_ctx
        self._exec_factory: Callable[[Any, Any], ExecutionContext] | None = None
        self._exec_arg1: Any = None
        self._exec_arg2: Any = None
        self._external_exec = exec_ctx is not None
        self._res: Response | None = None
        # Lazily created — most requests never use per-request variables
        # or staged headers, so they should not pay for the allocations.
        self._vars: dict[str, Any] | None = None
        self._header_ops: list[tuple[str, str, bool]] | None = None

    # -- response ----------------------------------------------------------

    @property
    def res(self) -> Response | None:
        return self._res

    @res.setter
    def res(self, value: Response | None) -> None:
        if value is not None and not isinstance(value, Response):
            raise TypeError(f"c.res must be a Response, got {type(value).__name__}")
        self._res = value

    # -- per-request variables (Hono's c.var) --------------------------------

    def get(self, key: str, default: Any = None) -> Any:
        variables = self._vars
        return default if variables is None else variables.get(key, default)

    def set(self, key: str, value: Any) -> None:
        if self._vars is None:
            self._vars = {}
        self._vars[key] = value

    # -- deferred work -------------------------------------------------------

    def _init_platform_execution(
        self,
        factory: Callable[[Any, Any], ExecutionContext],
        arg1: Any,
        arg2: Any,
    ) -> None:
        """Adapter hook: materialize an external execution context on access."""
        self._exec_factory = factory
        self._exec_arg1 = arg1
        self._exec_arg2 = arg2
        self._external_exec = True

    def _ensure_execution_context(self) -> ExecutionContext:
        exec_ctx = self._exec
        if exec_ctx is None:
            factory = self._exec_factory
            if factory is None:
                exec_ctx = ExecutionContext()
            else:
                exec_ctx = factory(self._exec_arg1, self._exec_arg2)
                self._exec_factory = None
                self._exec_arg1 = None
                self._exec_arg2 = None
            self._exec = exec_ctx
        return exec_ctx

    def wait_until(self, awaitable: Awaitable[Any]) -> None:
        """Run work after the response is sent (Workers ``ctx.waitUntil``)."""
        self._ensure_execution_context().wait_until(awaitable)

    # -- response header staging ----------------------------------------------

    def header(self, name: str, value: str, *, append: bool = False) -> None:
        """Stage a header for the final response (merged after the chain runs)."""
        if self._header_ops is None:
            self._header_ops = []
        self._header_ops.append((name, value, append))

    def _apply_header_ops(self) -> None:
        if self._res is None or self._header_ops is None:
            return
        for name, value, append in self._header_ops:
            if append:
                self._res.headers.append(name, value)
            else:
                self._res.headers.set(name, value)

    # -- response helpers -------------------------------------------------------

    def json(self, data: Any, status: int = 200, headers: HeadersArg = None) -> Response:
        # Build the response's Headers once, then add the trusted default in
        # place. The text stays unencoded for runtimes that accept it natively.
        text = dumps_compact(data)
        return Response(
            text,
            status,
            headers=headers,
            _default_content_type="application/json",
        )

    def text(self, text: str, status: int = 200, headers: HeadersArg = None) -> Response:
        return Response(text, status, headers=headers)

    def html(self, html: str, status: int = 200, headers: HeadersArg = None) -> Response:
        merged = Headers(headers)
        merged.set("content-type", "text/html;charset=utf-8")
        return Response(html, status, headers=merged)

    def body(self, body: BodyInit, status: int = 200, headers: HeadersArg = None) -> Response:
        return Response(body, status, headers=headers)

    def redirect(self, location: str, status: int = 302) -> Response:
        return Response.redirect(location, status)

    def not_found(self) -> Response:
        return problem(404)

    def event_stream(
        self,
        source: AsyncIterable[SSEMessage],
        status: int = 200,
        headers: HeadersArg = None,
    ) -> Response:
        """Server-Sent Events response (WHATWG HTML Standard)."""
        merged = Headers(headers)
        merged.set("content-type", "text/event-stream")
        if not merged.has("cache-control"):
            merged._append_trusted("cache-control", "no-cache")
        return Response(event_stream(source), status, headers=merged)

    def set_cookie(self, name: str, value: str, **attributes: Any) -> None:
        """Stage a ``Set-Cookie`` header (RFC 6265bis attributes as kwargs)."""
        self.header("set-cookie", serialize_set_cookie(name, value, **attributes), append=True)
