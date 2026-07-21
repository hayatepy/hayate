"""Handler timeout middleware (504 Gateway Timeout)."""

from __future__ import annotations

import asyncio

from ..context import Context, Middleware, Next
from ..exceptions import HTTPException


def timeout(*, seconds: float) -> Middleware:
    """Cancel the downstream chain after ``seconds`` and answer 504."""

    async def timeout_middleware(c: Context, next_: Next) -> None:
        try:
            async with asyncio.timeout(seconds):
                await next_()
        except TimeoutError:
            raise HTTPException(504, title="Gateway Timeout") from None

    return timeout_middleware
