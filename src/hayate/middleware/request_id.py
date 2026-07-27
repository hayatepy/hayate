"""Safe request correlation IDs across every Hayate runtime."""

from __future__ import annotations

import logging
import re
import uuid
from collections.abc import Callable
from contextvars import ContextVar
from typing import cast

from ..context import Context, Middleware, Next

type RequestIdGenerator = Callable[[Context], str]

_REQUEST_ID_PATTERN = re.compile(r"^[A-Za-z0-9._:+-]+$")
_CURRENT_REQUEST_ID: ContextVar[str | None] = ContextVar(
    "hayate_request_id",
    default=None,
)


def current_request_id() -> str | None:
    """Return the request ID bound to the current async execution context."""
    return _CURRENT_REQUEST_ID.get()


class RequestIdFilter(logging.Filter):
    """Attach the current request ID to standard-library log records."""

    def filter(self, record: logging.LogRecord) -> bool:
        value = current_request_id()
        if value is not None or "request_id" not in record.__dict__:
            record.__dict__["request_id"] = value
        return True


def _random_request_id(_: Context) -> str:
    return uuid.uuid4().hex


def request_id(
    *,
    generator: RequestIdGenerator | None = None,
    accept_incoming: bool = True,
    max_length: int = 128,
) -> Middleware:
    """Set one safe ``X-Request-ID`` in the context and response.

    A syntactically safe incoming ID is preserved by default. Invalid,
    oversized, or disabled incoming IDs are replaced by ``generator`` (a
    random UUID by default). Generated values use the same validation policy
    so they remain safe to include in response headers and application logs.
    """
    if max_length < 1:
        raise ValueError("max_length must be at least 1")
    generate = _random_request_id if generator is None else generator

    def valid(value: object) -> bool:
        return (
            isinstance(value, str)
            and len(value) <= max_length
            and _REQUEST_ID_PATTERN.fullmatch(value) is not None
        )

    async def request_id_middleware(c: Context, next_: Next) -> None:
        incoming = c.req.header("x-request-id") if accept_incoming else None
        value = incoming if valid(incoming) else generate(c)
        if not valid(value):
            raise ValueError(
                "request ID generator must return 1 to "
                f"{max_length} ASCII letters, digits, '.', '_', ':', '+', or '-'"
            )
        value = cast(str, value)
        c.set("request_id", value)
        # Stage before the inner chain so handled exceptions and 404 responses
        # carry the same correlation ID.
        c.header("x-request-id", value)
        token = _CURRENT_REQUEST_ID.set(value)
        restored = False

        def restore() -> None:
            nonlocal restored
            if not restored:
                _CURRENT_REQUEST_ID.reset(token)
                restored = True

        c._add_response_finalizer(restore)
        try:
            await next_()
        except Exception:
            # Hayate resolves ordinary exceptions after middleware unwinds.
            # Keep correlation bound for the application error handler.
            raise
        except BaseException:
            # Cancellation and other non-request exits never reach response
            # finalization, so restore their execution context immediately.
            restore()
            raise

    return request_id_middleware


__all__ = [
    "RequestIdFilter",
    "RequestIdGenerator",
    "current_request_id",
    "request_id",
]
