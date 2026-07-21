"""Request context: the single object handlers and middleware receive."""

from __future__ import annotations

import asyncio
import json as _json
import logging
from collections.abc import Awaitable, Callable, Iterable, Mapping
from typing import Any

from .body import BodyInit
from .exceptions import problem
from .headers import Headers
from .request import HayateRequest
from .response import Response

type Next = Callable[[], Awaitable[None]]
type HeadersArg = Headers | Mapping[str, str] | Iterable[tuple[str, str]] | None
type Handler = Callable[["Context"], Awaitable[Response | None]]
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
    __slots__ = ("_exec", "_header_ops", "_res", "_vars", "env", "req")

    def __init__(self, req: HayateRequest, env: Any, exec_ctx: ExecutionContext) -> None:
        self.req = req
        self.env = env
        self._exec = exec_ctx
        self._res: Response | None = None
        self._vars: dict[str, Any] = {}
        self._header_ops: list[tuple[str, str, bool]] = []

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
        return self._vars.get(key, default)

    def set(self, key: str, value: Any) -> None:
        self._vars[key] = value

    # -- deferred work -------------------------------------------------------

    def wait_until(self, awaitable: Awaitable[Any]) -> None:
        """Run work after the response is sent (Workers ``ctx.waitUntil``)."""
        self._exec.wait_until(awaitable)

    # -- response header staging ----------------------------------------------

    def header(self, name: str, value: str, *, append: bool = False) -> None:
        """Stage a header for the final response (merged after the chain runs)."""
        self._header_ops.append((name, value, append))

    def _apply_header_ops(self) -> None:
        if self._res is None:
            return
        for name, value, append in self._header_ops:
            if append:
                self._res.headers.append(name, value)
            else:
                self._res.headers.set(name, value)

    # -- response helpers -------------------------------------------------------

    def json(self, data: Any, status: int = 200, headers: HeadersArg = None) -> Response:
        merged = Headers(headers)
        if not merged.has("content-type"):
            merged._append_trusted("content-type", "application/json")
        payload = _json.dumps(data, ensure_ascii=False, separators=(",", ":"))
        return Response(payload, status, headers=merged)

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
