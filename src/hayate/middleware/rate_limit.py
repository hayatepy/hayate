"""Request rate limiting with standard quota advertisement.

Emits the ``RateLimit`` / ``RateLimit-Policy`` fields of
draft-ietf-httpapi-ratelimit-headers-11 (Structured Fields: one named policy,
``q``/``w`` on the policy, ``r``/``t`` on the live field) and answers
exhausted quotas with 429 + ``Retry-After`` (RFC 6585 / RFC 9110).

The caller must supply ``key``: extracting a client identity (peer IP behind
a proxy, an API key, a signed-in user id) is a trust-boundary decision the
framework cannot make safely on its own. Returning ``None`` skips limiting
for that request.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Protocol

from ..context import Context, Middleware, Next
from ..exceptions import HTTPException

_SWEEP_THRESHOLD = 4096


class RateLimitStore(Protocol):
    """Counting backend. The bundled store is in-memory and per-process;
    inject an implementation over shared storage when you scale out."""

    async def hit(self, key: str, window: int) -> tuple[int, int]:
        """Record one hit; return (hits in the current window, seconds left)."""
        ...


class MemoryRateLimitStore:
    """Fixed-window counters in a dict (per process, zero dependencies)."""

    def __init__(self, *, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
        self._buckets: dict[str, tuple[float, int]] = {}

    async def hit(self, key: str, window: int) -> tuple[int, int]:
        now = self._clock()
        started, count = self._buckets.get(key, (now, 0))
        if now - started >= window:
            started, count = now, 0
        count += 1
        self._buckets[key] = (started, count)
        if len(self._buckets) > _SWEEP_THRESHOLD:
            self._sweep(now, window)
        return count, max(0, int(started + window - now) + 1)

    def _sweep(self, now: float, window: int) -> None:
        expired = [k for k, (started, _) in self._buckets.items() if now - started >= window]
        for k in expired:
            del self._buckets[k]


def rate_limit(
    *,
    limit: int,
    window: int,
    key: Callable[[Context], str | None],
    name: str = "default",
    store: RateLimitStore | None = None,
) -> Middleware:
    """Allow ``limit`` requests per ``key`` per ``window`` seconds.

    ``key`` maps the request to a quota partition (return ``None`` to skip).
    Quota state is advertised on every response; exceeding it raises 429
    with ``Retry-After``.
    """
    if limit < 1:
        raise ValueError("limit must be >= 1")
    if window < 1:
        raise ValueError("window must be >= 1")
    backend = store if store is not None else MemoryRateLimitStore()
    policy_value = f'"{name}";q={limit};w={window}'

    async def rate_limit_middleware(c: Context, next_: Next) -> None:
        partition = key(c)
        if partition is None:
            await next_()
            return

        count, reset = await backend.hit(partition, window)
        remaining = max(0, limit - count)
        live_value = f'"{name}";r={remaining};t={reset}'

        if count > limit:
            raise HTTPException(
                429,
                title="Too Many Requests",
                headers={
                    "ratelimit": live_value,
                    "ratelimit-policy": policy_value,
                    "retry-after": str(reset),
                },
            )

        c.header("ratelimit", live_value)
        c.header("ratelimit-policy", policy_value)
        await next_()

    return rate_limit_middleware
