"""Request logging middleware."""

from __future__ import annotations

import logging
import time

from ..context import Context, Middleware, Next
from ..jsonutil import dumps_compact


def logger(log: logging.Logger | None = None, *, structured: bool = False) -> Middleware:
    """Log one access event after each request.

    The default preserves the human-readable
    ``<method> <path> -> <status> (<ms>)`` message. ``structured=True`` emits
    compact JSON with stable, parser-friendly fields. Both modes attach the
    same fields to the standard-library ``LogRecord``.
    """
    target = log if log is not None else logging.getLogger("hayate.request")

    async def logger_middleware(c: Context, next_: Next) -> None:
        start = time.perf_counter()
        try:
            await next_()
        finally:
            elapsed_ms = (time.perf_counter() - start) * 1000
            status = c.res.status if c.res is not None else 500
            request_id = c.get("request_id")
            fields = {
                "event": "http_request",
                "method": c.req.method,
                "path": c.req.url.pathname,
                "status": status,
                "duration_ms": round(elapsed_ms, 3),
                "request_id": request_id if isinstance(request_id, str) else None,
            }
            if structured:
                target.info("%s", dumps_compact(fields), extra=fields)
            else:
                target.info(
                    "%s %s -> %d (%.1fms)",
                    fields["method"],
                    fields["path"],
                    fields["status"],
                    elapsed_ms,
                    extra=fields,
                )

    return logger_middleware
