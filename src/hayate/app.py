"""The ``Hayate`` application: routing, middleware composition, error handling.

The core is I/O-free: ``fetch(Request) -> Response`` is the only entry
point, and adapters (ASGI, Workers, ...) translate transport events into
that call. This purity is what makes ``app.request()`` testing and
multi-runtime support fall out for free.
"""

from __future__ import annotations

import asyncio
import inspect
import json as _json
import logging
import traceback
from collections.abc import Awaitable, Callable
from functools import wraps
from typing import TYPE_CHECKING, Any

from .context import Context, ErrorHandler, ExecutionContext, Handler, HeadersArg, Middleware
from .exceptions import HTTPException, problem
from .headers import Headers
from .request import HayateRequest, Request
from .response import Response
from .router import Route, Router
from .urlpattern import URLPattern

if TYPE_CHECKING:
    from .body import BodyInit

_logger = logging.getLogger("hayate")


async def _default_not_found(c: Context) -> Response:
    return problem(404)


def _ensure_async_handler(fn: Callable[..., Any]) -> Handler:
    """Normalize handlers to coroutine functions (single execution path).

    Sync handlers run in a thread via ``asyncio.to_thread``. This is an
    ASGI-side convenience only — Pyodide (Workers) has no threads.
    """
    if inspect.iscoroutinefunction(fn):
        return fn

    @wraps(fn)
    async def run_in_thread(c: Context) -> Response | None:
        return await asyncio.to_thread(fn, c)

    return run_in_thread


def _check_middleware(fn: Any) -> None:
    if not inspect.iscoroutinefunction(fn):
        raise TypeError("middleware must be async: async def middleware(c, next)")


class Hayate:
    def __init__(self, *, env: Any = None, debug: bool = False) -> None:
        self._router = Router()
        self._middleware: list[tuple[URLPattern | None, Middleware]] = []
        self._env = env
        self._debug = debug
        self._not_found_handler: Handler = _default_not_found
        self._error_handler: ErrorHandler | None = None
        self._on_start: list[Callable[[], Any]] = []
        self._on_stop: list[Callable[[], Any]] = []
        self._asgi: Callable[..., Awaitable[None]] | None = None

    # -- route registration --------------------------------------------------

    def on(
        self, method: str, path: str, *middleware: Middleware
    ) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
        upper = method.upper()
        for mw in middleware:
            _check_middleware(mw)

        def decorator(fn: Callable[..., Any]) -> Callable[..., Any]:
            handler = _ensure_async_handler(fn)
            self._router.add(Route(upper, path, handler, tuple(middleware)))
            return fn

        return decorator

    def get(self, path: str, *middleware: Middleware):
        return self.on("GET", path, *middleware)

    def post(self, path: str, *middleware: Middleware):
        return self.on("POST", path, *middleware)

    def put(self, path: str, *middleware: Middleware):
        return self.on("PUT", path, *middleware)

    def delete(self, path: str, *middleware: Middleware):
        return self.on("DELETE", path, *middleware)

    def patch(self, path: str, *middleware: Middleware):
        return self.on("PATCH", path, *middleware)

    def options(self, path: str, *middleware: Middleware):
        return self.on("OPTIONS", path, *middleware)

    def head(self, path: str, *middleware: Middleware):
        return self.on("HEAD", path, *middleware)

    # -- middleware ------------------------------------------------------------

    def use(self, arg: str | Middleware, middleware: Middleware | None = None):
        """Register middleware, optionally scoped to a URLPattern.

        Forms: ``app.use(mw)``, ``@app.use``, ``app.use("/admin/*", mw)``,
        and ``@app.use("/admin/*")``.
        """
        if callable(arg):
            _check_middleware(arg)
            self._middleware.append((None, arg))
            return arg
        pattern = URLPattern(arg)
        if middleware is not None:
            _check_middleware(middleware)
            self._middleware.append((pattern, middleware))
            return middleware

        def decorator(fn: Middleware) -> Middleware:
            _check_middleware(fn)
            self._middleware.append((pattern, fn))
            return fn

        return decorator

    # -- hooks -------------------------------------------------------------------

    def not_found(self, fn: Callable[..., Any]) -> Callable[..., Any]:
        self._not_found_handler = _ensure_async_handler(fn)
        return fn

    def on_error(self, fn: ErrorHandler) -> ErrorHandler:
        if not inspect.iscoroutinefunction(fn):
            raise TypeError("error handler must be async: async def handler(err, c)")
        self._error_handler = fn
        return fn

    def on_start(self, fn: Callable[[], Any]) -> Callable[[], Any]:
        self._on_start.append(fn)
        return fn

    def on_stop(self, fn: Callable[[], Any]) -> Callable[[], Any]:
        self._on_stop.append(fn)
        return fn

    # -- the core ------------------------------------------------------------------

    async def fetch(
        self, request: Request, env: Any = None, ctx: ExecutionContext | None = None
    ) -> Response:
        """Handle one request. The only entry point; everything else adapts to it."""
        own_ctx = ctx is None
        exec_ctx = ctx if ctx is not None else ExecutionContext()
        c = Context(HayateRequest(request), env if env is not None else self._env, exec_ctx)
        try:
            await self._dispatch(c)
        except Exception as exc:
            c.res = await self._handle_error(exc, c)
        if c.res is None:
            c.res = problem(500, detail="no response was produced")
        if c._header_ops:
            c._apply_header_ops()
        if own_ctx and exec_ctx._tasks:
            await exec_ctx._drain()
        return c.res

    async def _dispatch(self, c: Context) -> None:
        path = c.req.url.pathname
        method = c.req.method
        matched = self._router.match(method, path)
        if matched is None and method == "HEAD":
            matched = self._router.match("GET", path)

        if self._middleware:
            scoped = [
                mw for pattern, mw in self._middleware if pattern is None or pattern.test(path)
            ]
        else:
            scoped = []
        if matched is not None:
            route, params = matched
            c.req._params = params
            chain = scoped + list(route.middleware) if route.middleware else scoped
            handler = route.handler
        else:
            # No route: middleware still runs (CORS etc. apply to 404/405 too).
            chain = scoped
            allowed = self._router.allowed_methods(path)
            if allowed:
                allow_value = ", ".join(allowed)

                async def handler(_c: Context) -> Response | None:
                    raise HTTPException(405, headers={"allow": allow_value})

            else:
                handler = self._not_found_handler
        await self._compose(c, chain, handler)

    async def _compose(self, c: Context, chain: list[Middleware], handler: Handler) -> None:
        if not chain:
            # Hot path: no middleware, no dispatch closures.
            result = await handler(c)
            if result is not None:
                if not isinstance(result, Response):
                    raise TypeError(
                        f"handler must return a Response or None, got {type(result).__name__}"
                    )
                c.res = result
            elif c.res is None:
                raise TypeError("handler returned None and no response was set on c.res")
            return

        async def dispatch(index: int) -> None:
            if index == len(chain):
                result = await handler(c)
                if result is not None:
                    if not isinstance(result, Response):
                        raise TypeError(
                            f"handler must return a Response or None, got {type(result).__name__}"
                        )
                    c.res = result
                elif c.res is None:
                    raise TypeError("handler returned None and no response was set on c.res")
                return

            called = False

            async def next_() -> None:
                nonlocal called
                if called:
                    raise RuntimeError("next() called multiple times")
                called = True
                await dispatch(index + 1)

            result = await chain[index](c, next_)
            if isinstance(result, Response):
                c.res = result

        await dispatch(0)

    async def _handle_error(self, exc: Exception, c: Context) -> Response:
        if self._error_handler is not None:
            try:
                return await self._error_handler(exc, c)
            except Exception:
                _logger.exception("error handler raised; falling back to the default")
        if isinstance(exc, HTTPException):
            return exc.to_response()
        _logger.exception("unhandled error for %s %s", c.req.method, c.req.url.pathname)
        detail = "".join(traceback.format_exception(exc)) if self._debug else None
        return problem(500, detail=detail)

    # -- testing ---------------------------------------------------------------------

    async def request(
        self,
        path: str = "/",
        *,
        method: str = "GET",
        headers: HeadersArg = None,
        body: BodyInit = None,
        json: Any = None,
    ) -> Response:
        """Call the app directly — no server, no adapter. The primary test API."""
        merged = Headers(headers)
        if json is not None:
            if body is not None:
                raise TypeError("pass either body or json, not both")
            body = _json.dumps(json, ensure_ascii=False)
            if not merged.has("content-type"):
                merged.set("content-type", "application/json")
        if "://" in path:
            url = path
        else:
            url = f"http://localhost{path if path.startswith('/') else '/' + path}"
        return await self.fetch(Request(url, method=method, headers=merged, body=body))

    # -- ASGI --------------------------------------------------------------------------

    async def __call__(self, scope: dict[str, Any], receive: Any, send: Any) -> None:
        if self._asgi is None:
            from .adapters.asgi import ASGIAdapter

            self._asgi = ASGIAdapter(self)
        await self._asgi(scope, receive, send)
