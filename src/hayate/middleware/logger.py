"""Request logging middleware."""

from __future__ import annotations

import logging
import time

from ..context import Context, Middleware, Next


def logger(log: logging.Logger | None = None) -> Middleware:
    """Log ``<method> <path> -> <status> (<ms>)`` at INFO level."""
    target = log if log is not None else logging.getLogger("hayate.request")

    async def logger_middleware(c: Context, next_: Next) -> None:
        start = time.perf_counter()
        try:
            await next_()
        finally:
            elapsed_ms = (time.perf_counter() - start) * 1000
            status = c.res.status if c.res is not None else 500
            target.info(
                "%s %s -> %d (%.1fms)", c.req.method, c.req.url.pathname, status, elapsed_ms
            )

    return logger_middleware
