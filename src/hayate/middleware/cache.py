"""In-process response micro-cache with RFC 9111 headers.

Caches successful buffered GET responses per ``pathname + search`` for
``max_age`` seconds, stamps ``Cache-Control`` and ``Age``, and serves
hits without re-running the handler. Process-local by design (each
worker has its own cache); shared caches (e.g. the Workers Cache API)
are an adapter concern.
"""

from __future__ import annotations

import time

from ..context import Context, Middleware, Next
from ..response import Response

type _Entry = tuple[float, float, int, list[tuple[str, str]], bytes | None]


def cache(*, max_age: int, private: bool = False, max_entries: int = 1024) -> Middleware:
    """In-memory micro-cache with ``Cache-Control`` / ``Age`` semantics (RFC 9111)."""

    store: dict[str, _Entry] = {}
    directive = f"{'private' if private else 'public'}, max-age={max_age}"

    async def cache_middleware(c: Context, next_: Next) -> None:
        if c.req.method != "GET":
            await next_()
            return
        url = c.req.url
        key = url.pathname + url.search
        now = time.monotonic()
        entry = store.get(key)
        if entry is not None:
            expires_at, stored_at, status, header_pairs, body = entry
            if expires_at > now:
                response = Response(body, status, headers=header_pairs)
                response.headers.set("age", str(int(now - stored_at)))
                c.res = response
                return
            del store[key]

        await next_()
        res = c.res
        if res is None or res.status != 200:
            return
        body = res.body
        if not (body is None or isinstance(body, bytes)):
            return  # streams are not buffered just to cache them
        res.headers.set("cache-control", directive)
        if len(store) >= max_entries:
            store.pop(next(iter(store)))
        store[key] = (now + max_age, now, res.status, res.headers.raw(), body)

    return cache_middleware
