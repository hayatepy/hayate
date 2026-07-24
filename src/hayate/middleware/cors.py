"""CORS middleware — semantics per the Fetch Standard's CORS protocol."""

from __future__ import annotations

import inspect
from collections.abc import Awaitable, Callable, Sequence

from ..context import Context, Middleware, Next
from ..headers import Headers
from ..response import Response
from ._internal import append_vary

type OriginOption = str | Sequence[str] | Callable[[str], str | None]
type ContextOriginResolver = Callable[[Context, str], str | None | Awaitable[str | None]]


def cors(
    *,
    origin: OriginOption = "*",
    origin_resolver: ContextOriginResolver | None = None,
    allow_methods: Sequence[str] = ("GET", "HEAD", "PUT", "POST", "DELETE", "PATCH"),
    allow_headers: Sequence[str] = (),
    expose_headers: Sequence[str] = (),
    credentials: bool = False,
    max_age: int | None = None,
) -> Middleware:
    """Cross-Origin Resource Sharing response headers, including preflight.

    ``origin_resolver`` receives the request Context, so Workers applications
    can resolve allowlists from ``c.env`` without replacing this middleware.
    """
    if origin_resolver is not None and origin != "*":
        raise ValueError("pass either origin or origin_resolver, not both")

    def resolve_origin(request_origin: str) -> str | None:
        if callable(origin):
            return origin(request_origin)
        if isinstance(origin, str):
            if origin == "*":
                # The wildcard is invalid with credentials; echo the origin instead.
                return request_origin if credentials else "*"
            return origin if request_origin == origin else None
        return request_origin if request_origin in origin else None

    async def cors_middleware(c: Context, next_: Next) -> None:
        request_origin = c.req.header("origin")
        if request_origin is None:
            await next_()
            return
        if origin_resolver is None:
            allow_origin = resolve_origin(request_origin)
        else:
            resolved = origin_resolver(c, request_origin)
            allow_origin = await resolved if inspect.isawaitable(resolved) else resolved

        is_preflight = (
            c.req.method == "OPTIONS" and c.req.header("access-control-request-method") is not None
        )
        if is_preflight:
            headers = Headers()
            if allow_origin is not None:
                headers.set("access-control-allow-origin", allow_origin)
                if credentials:
                    headers.set("access-control-allow-credentials", "true")
                headers.set("access-control-allow-methods", ", ".join(allow_methods))
                requested = c.req.header("access-control-request-headers")
                allowed = ", ".join(allow_headers) if allow_headers else requested
                if allowed:
                    headers.set("access-control-allow-headers", allowed)
                if max_age is not None:
                    headers.set("access-control-max-age", str(max_age))
            for field in (
                "origin",
                "access-control-request-method",
                "access-control-request-headers",
            ):
                append_vary(headers, field)
            c.res = Response(None, 204, headers=headers)
            return

        await next_()
        res = c.res
        if res is None or allow_origin is None:
            return
        res.headers.set("access-control-allow-origin", allow_origin)
        if credentials:
            res.headers.set("access-control-allow-credentials", "true")
        if expose_headers:
            res.headers.set("access-control-expose-headers", ", ".join(expose_headers))
        if allow_origin != "*":
            append_vary(res.headers, "origin")

    return cors_middleware
