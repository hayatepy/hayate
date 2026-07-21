"""Request body size limiting (413 Content Too Large, RFC 9110)."""

from __future__ import annotations

from collections.abc import AsyncIterable, AsyncIterator

from ..context import Context, Middleware, Next
from ..exceptions import HTTPException


def _too_large() -> HTTPException:
    return HTTPException(413, title="Content Too Large")


async def _limited(source: AsyncIterable[bytes], max_size: int) -> AsyncIterator[bytes]:
    total = 0
    async for chunk in source:
        total += len(chunk)
        if total > max_size:
            raise _too_large()
        yield chunk


def body_limit(*, max_size: int) -> Middleware:
    """Reject request bodies larger than ``max_size`` bytes.

    Declared sizes (``content-length``) are rejected up front; chunked
    or streamed bodies are enforced as they are read.
    """

    async def body_limit_middleware(c: Context, next_: Next) -> None:
        raw = c.req.raw
        declared = raw.headers.get("content-length")
        if declared is not None and declared.isdigit() and int(declared) > max_size:
            raise _too_large()
        if raw._buffer is not None and len(raw._buffer) > max_size:
            raise _too_large()
        if raw._stream is not None:
            # Built-in middleware may reach into the body internals.
            raw._stream = _limited(raw._stream, max_size)
        await next_()

    return body_limit_middleware
