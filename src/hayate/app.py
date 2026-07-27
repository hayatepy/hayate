"""The ``Hayate`` application: routing, middleware composition, error handling.

The core is I/O-free: ``fetch(Request) -> Response`` is the only entry
point, and adapters (ASGI, Workers, ...) translate transport events into
that call. This purity is what makes ``app.request()`` testing and
multi-runtime support fall out for free.
"""

from __future__ import annotations

import asyncio
import inspect
import logging
import sys
import traceback
from collections.abc import Awaitable, Callable, Sequence
from functools import wraps
from types import CoroutineType
from typing import TYPE_CHECKING, Any, cast, overload

from .context import Context, ErrorHandler, ExecutionContext, Handler, HeadersArg, Middleware
from .exceptions import HTTPException, problem
from .headers import Headers
from .jsonutil import dumps_compact
from .request import HayateRequest, Request
from .response import Response
from .router import WEBSOCKET_METHOD, Route, Router
from .urlpattern import URLPattern

if TYPE_CHECKING:
    from .body import BodyInit

_logger = logging.getLogger("hayate")
_INLINE_SYNC_HANDLERS = sys.platform == "emscripten"
_EMPTY_MIDDLEWARE: tuple[Middleware, ...] = ()


async def _default_not_found(c: Context) -> Response:
    return problem(404)


def _prepare_handler(fn: Callable[..., Any]) -> tuple[Handler, bool]:
    """Prepare a handler for the active Python runtime.

    Native Python sends sync handlers to a thread. Pyodide has no threads,
    so its sync handlers execute inline without manufacturing a coroutine.
    """
    if inspect.iscoroutinefunction(fn):
        return fn, False
    if _INLINE_SYNC_HANDLERS:
        return fn, True

    @wraps(fn)
    async def run_in_thread(c: Context) -> Response | None:
        return await asyncio.to_thread(fn, c)

    return run_in_thread, False


def _check_middleware(fn: Any) -> None:
    if not inspect.iscoroutinefunction(fn):
        raise TypeError("middleware must be async: async def middleware(c, next)")


def _check_error_handler(fn: Any) -> None:
    if not inspect.iscoroutinefunction(fn):
        raise TypeError("error handler must be async: async def handler(err, c)")


def _finish_adapter_output(
    response: Response,
    finish: Callable[[Response, Any, Any], Any] | None,
    arg1: Any,
    arg2: Any,
) -> Any:
    return response if finish is None else finish(response, arg1, arg2)


class Hayate:
    """The application: routing, middleware, and the runtime-agnostic ``fetch()`` core."""

    def __init__(self, *, env: Any = None, debug: bool = False) -> None:
        self._router = Router()
        self._middleware: list[tuple[URLPattern | None, Middleware]] = []
        # Stage 2 (DESIGN §14.1-2): while every middleware is unscoped, the
        # per-request chain is this shared list — no per-request filtering.
        self._plain_chain: list[Middleware] | None = []
        self._env = env
        self._debug = debug
        self._not_found_handler: Handler = _default_not_found
        self._not_found_inline = False
        self._error_handler: ErrorHandler | None = None
        self._on_start: list[Callable[[], Any]] = []
        self._on_stop: list[Callable[[], Any]] = []
        self._asgi: Callable[..., Awaitable[None]] | None = None

    @property
    def routes(self) -> tuple[Route, ...]:
        """Every registered route in registration order (read-only).

        The introspection surface for tooling (OpenAPI generation, route
        listings): each ``Route`` exposes ``method``, ``pattern``,
        ``handler``, and ``middleware``. Mutating the tuple does not
        affect routing.
        """
        return tuple(self._router._all)

    # -- route registration --------------------------------------------------

    def on[F: Callable[..., Any]](
        self, method: str, path: str, *middleware: Middleware
    ) -> Callable[[F], F]:
        upper = method.upper()
        for mw in middleware:
            _check_middleware(mw)

        def decorator(fn: F) -> F:
            handler, inline = _prepare_handler(fn)
            self._router.add(Route(upper, path, handler, tuple(middleware), inline=inline))
            return fn

        return decorator

    def get[F: Callable[..., Any]](self, path: str, *middleware: Middleware) -> Callable[[F], F]:
        return self.on("GET", path, *middleware)

    def post[F: Callable[..., Any]](self, path: str, *middleware: Middleware) -> Callable[[F], F]:
        return self.on("POST", path, *middleware)

    def put[F: Callable[..., Any]](self, path: str, *middleware: Middleware) -> Callable[[F], F]:
        return self.on("PUT", path, *middleware)

    def delete[F: Callable[..., Any]](self, path: str, *middleware: Middleware) -> Callable[[F], F]:
        return self.on("DELETE", path, *middleware)

    def patch[F: Callable[..., Any]](self, path: str, *middleware: Middleware) -> Callable[[F], F]:
        return self.on("PATCH", path, *middleware)

    def options[F: Callable[..., Any]](
        self, path: str, *middleware: Middleware
    ) -> Callable[[F], F]:
        return self.on("OPTIONS", path, *middleware)

    def head[F: Callable[..., Any]](self, path: str, *middleware: Middleware) -> Callable[[F], F]:
        return self.on("HEAD", path, *middleware)

    def ws[F: Callable[..., Any]](self, path: str) -> Callable[[F], F]:
        """Register a WebSocket route: ``async def handler(c, ws)``."""

        def decorator(fn: F) -> F:
            if not inspect.iscoroutinefunction(fn):
                raise TypeError("websocket handlers must be async")
            self._router.add(Route(WEBSOCKET_METHOD, path, fn, ()))
            return fn

        return decorator

    # -- middleware ------------------------------------------------------------

    @overload
    def use[M: Middleware](self, arg: M, middleware: None = None) -> M: ...

    @overload
    def use[M: Middleware](self, arg: str, middleware: M) -> M: ...

    @overload
    def use[M: Middleware](self, arg: str, middleware: None = None) -> Callable[[M], M]: ...

    def use(
        self, arg: str | Middleware, middleware: Middleware | None = None
    ) -> Middleware | Callable[[Middleware], Middleware]:
        """Register middleware, optionally scoped to a URLPattern.

        Forms: ``app.use(mw)``, ``@app.use``, ``app.use("/admin/*", mw)``,
        and ``@app.use("/admin/*")``.
        """
        if callable(arg):
            self._register_middleware(None, arg)
            return arg
        pattern = URLPattern(arg)
        if middleware is not None:
            self._register_middleware(pattern, middleware)
            return middleware

        def decorator(fn: Middleware) -> Middleware:
            self._register_middleware(pattern, fn)
            return fn

        return decorator

    def _register_middleware(self, pattern: URLPattern | None, fn: Middleware) -> None:
        _check_middleware(fn)
        self._middleware.append((pattern, fn))
        if pattern is None:
            if self._plain_chain is not None:
                self._plain_chain.append(fn)
        else:
            # Scoped middleware defeats the precomputed chain.
            self._plain_chain = None

    # -- hooks -------------------------------------------------------------------

    def not_found[F: Callable[..., Any]](self, fn: F) -> F:
        self._not_found_handler, self._not_found_inline = _prepare_handler(fn)
        return fn

    def on_error[F: ErrorHandler](self, fn: F) -> F:
        _check_error_handler(fn)
        self._error_handler = fn
        return fn

    def on_start[F: Callable[[], Any]](self, fn: F) -> F:
        self._on_start.append(fn)
        return fn

    def on_stop[F: Callable[[], Any]](self, fn: F) -> F:
        self._on_stop.append(fn)
        return fn

    # -- the core ------------------------------------------------------------------

    async def fetch(
        self, request: Request, env: Any = None, ctx: ExecutionContext | None = None
    ) -> Response:
        """Handle one request. The only entry point; everything else adapts to it.

        Background work (``c.wait_until``): with an explicit ``ctx`` the
        caller owns draining it (Workers-style). Without one, pending work
        rides on the returned response and is drained by the adapter or
        ``app.request()`` after the response is delivered.
        """
        c = Context(HayateRequest(request), env if env is not None else self._env, ctx)
        try:
            matched = None
            if not self._middleware:
                method = request.method
                path = request._pathname_for_routing()
                matched = self._router.match(method, path)
                if matched is None and method == "HEAD":
                    matched = self._router.match("GET", path)

            if matched is not None:
                route, params = matched
                c.req._params = params
                if route.middleware:
                    await self._compose(c, route.middleware, route.handler, route.inline)
                else:
                    result = (
                        cast(Response | None, route.handler(c))
                        if route.inline
                        else await cast(Awaitable[Response | None], route.handler(c))
                    )
                    self._accept_handler_result(c, result)
            else:
                chain, handler, inline = self._resolve(c)
                if chain:
                    await self._compose(c, chain, handler, inline)
                else:
                    result = (
                        cast(Response | None, handler(c))
                        if inline
                        else await cast(Awaitable[Response | None], handler(c))
                    )
                    self._accept_handler_result(c, result)
        except Exception as exc:
            c._res = await self._handle_error(exc, c)
        return self._finalize_context(c)

    def _fetch_for_adapter(
        self,
        request: Request,
        env: Any,
        ctx: ExecutionContext | None,
        *,
        _exec_factory: Callable[[Any, Any], ExecutionContext] | None = None,
        _exec_arg1: Any = None,
        _exec_arg2: Any = None,
        _finish: Callable[[Response, Any, Any], Any] | None = None,
        _finish_arg1: Any = None,
        _finish_arg2: Any = None,
    ) -> Any:
        """Adapter path that stays synchronous and can fuse final conversion."""
        c = (
            Context(HayateRequest(request), env, ctx)
            if _exec_factory is None
            else Context._from_adapter(
                HayateRequest(request),
                env,
                _exec_factory,
                _exec_arg1,
                _exec_arg2,
            )
        )
        chain: Sequence[Middleware]
        handler: Handler
        inline: bool
        try:
            if not self._middleware:
                method = request.method
                matched = self._router.match(method, request._pathname_for_routing())
                if matched is None and method == "HEAD":
                    matched = self._router.match("GET", request._pathname_for_routing())
                if matched is not None:
                    route, params = matched
                    c.req._params = params
                    chain = route.middleware or _EMPTY_MIDDLEWARE
                    handler = route.handler
                    inline = route.inline
                else:
                    chain, handler, inline = self._resolve(c)
            else:
                chain, handler, inline = self._resolve(c)
        except Exception as exc:

            async def failed(error: Exception = exc) -> Any:
                c._res = await self._handle_error(error, c)
                output = _finish_adapter_output(
                    self._finalize_context(c),
                    _finish,
                    _finish_arg1,
                    _finish_arg2,
                )
                return await output if isinstance(output, CoroutineType) else output

            return failed()
        if not chain and inline:
            try:
                result = cast(Response | None, handler(c))
                self._accept_handler_result(c, result)
            except Exception as exc:

                async def failed(error: Exception = exc) -> Any:
                    c._res = await self._handle_error(error, c)
                    output = _finish_adapter_output(
                        self._finalize_context(c),
                        _finish,
                        _finish_arg1,
                        _finish_arg2,
                    )
                    return await output if isinstance(output, CoroutineType) else output

                return failed()
            return _finish_adapter_output(
                self._finalize_context(c),
                _finish,
                _finish_arg1,
                _finish_arg2,
            )

        return self._complete_adapter_request(
            c,
            chain,
            handler,
            inline,
            _finish,
            _finish_arg1,
            _finish_arg2,
        )

    async def _complete_adapter_request(
        self,
        c: Context,
        chain: Sequence[Middleware],
        handler: Handler,
        inline: bool,
        finish: Callable[[Response, Any, Any], Any] | None,
        finish_arg1: Any,
        finish_arg2: Any,
    ) -> Any:
        try:
            if chain:
                await self._compose(c, chain, handler, inline)
            else:
                result = await cast(Awaitable[Response | None], handler(c))
                self._accept_handler_result(c, result)
        except Exception as exc:
            c._res = await self._handle_error(exc, c)
        output = _finish_adapter_output(
            self._finalize_context(c),
            finish,
            finish_arg1,
            finish_arg2,
        )
        return await output if isinstance(output, CoroutineType) else output

    @staticmethod
    def _finalize_context(c: Context) -> Response:
        if c._res is None:
            c._res = problem(500, detail="no response was produced")
        if c._header_ops:
            c._apply_header_ops()
        response = c._res
        if not c._external_exec and c._exec is not None:
            response._background = c._exec
        return response

    def _resolve(self, c: Context) -> tuple[Sequence[Middleware], Handler, bool]:
        """Resolve a request synchronously; only handlers cross an await."""
        path = c.req._pathname_for_routing()
        method = c.req.method
        matched = self._router.match(method, path)
        if matched is None and method == "HEAD":
            matched = self._router.match("GET", path)

        if not self._middleware:
            scoped: Sequence[Middleware] = _EMPTY_MIDDLEWARE
        elif self._plain_chain is not None:
            scoped = self._plain_chain
        else:
            scoped = [
                mw for pattern, mw in self._middleware if pattern is None or pattern.test(path)
            ]
        if matched is not None:
            route, params = matched
            c.req._params = params
            chain = [*scoped, *route.middleware] if route.middleware else scoped
            handler = route.handler
            inline = route.inline
        else:
            # No route: middleware still runs (CORS etc. apply to 404/405 too).
            chain = scoped
            allowed = self._router.allowed_methods(path)
            if allowed:
                allow_value = ", ".join(allowed)

                async def handler(_c: Context) -> Response | None:
                    raise HTTPException(405, headers={"allow": allow_value})

                inline = False
            else:
                handler = self._not_found_handler
                inline = self._not_found_inline
        return chain, handler, inline

    @staticmethod
    def _accept_handler_result(c: Context, result: Response | None) -> None:
        if result is not None:
            if not isinstance(result, Response):
                raise TypeError(
                    f"handler must return a Response or None, got {type(result).__name__}"
                )
            c._res = result
        elif c._res is None:
            raise TypeError("handler returned None and no response was set on c.res")

    async def _compose(
        self, c: Context, chain: Sequence[Middleware], handler: Handler, inline: bool
    ) -> None:
        async def dispatch(index: int) -> None:
            if index == len(chain):
                result = (
                    cast(Response | None, handler(c))
                    if inline
                    else await cast(Awaitable[Response | None], handler(c))
                )
                self._accept_handler_result(c, result)
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
            body = dumps_compact(json)
            if not merged.has("content-type"):
                merged.set("content-type", "application/json")
        if "://" in path:
            url = path
        else:
            url = f"http://localhost{path if path.startswith('/') else '/' + path}"
        response = await self.fetch(Request(url, method=method, headers=merged, body=body))
        background = response._background
        if background is not None:
            response._background = None
            await background._drain()
        return response

    # -- ASGI --------------------------------------------------------------------------

    async def __call__(self, scope: dict[str, Any], receive: Any, send: Any) -> None:
        if self._asgi is None:
            from .adapters.asgi import ASGIAdapter

            self._asgi = ASGIAdapter(self)
        await self._asgi(scope, receive, send)
