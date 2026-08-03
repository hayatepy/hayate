"""Identity-aware, byte-bounded response micro-cache with RFC 9111 headers.

Caches successful buffered GET responses per ``pathname + search`` for
``max_age`` seconds, stamps ``Cache-Control`` and ``Age``, and serves
hits without re-running the handler. Process-local by design (each
worker has its own cache); shared caches (e.g. the Workers Cache API)
are an adapter concern.

Credential-bearing requests bypass the cache unless the caller supplies an
explicit identity key. Private caches require that key, so one user's response
cannot silently occupy the URL-only partition used by another user.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass

from ..context import Context, Middleware, Next
from ..response import Response


@dataclass(frozen=True, slots=True)
class _Entry:
    expires_at: float
    stored_at: float
    status: int
    headers: list[tuple[str, str]]
    body: bytes | None
    size: int


type _CacheKey = tuple[str | None, str]


def _entry_size(headers: list[tuple[str, str]], body: bytes | None) -> int:
    header_bytes = sum(
        len(name.encode("utf-8")) + len(value.encode("utf-8")) + 4 for name, value in headers
    )
    return header_bytes + (len(body) if body is not None else 0)


def cache(
    *,
    max_age: int,
    private: bool = False,
    max_entries: int = 1024,
    max_bytes: int = 16 * 1024 * 1024,
    key: Callable[[Context], str | None] | None = None,
) -> Middleware:
    """In-memory micro-cache with ``Cache-Control`` / ``Age`` semantics.

    ``max_bytes`` bounds the combined cached body and header bytes. Requests
    with ``Authorization``, ``Proxy-Authorization``, or ``Cookie`` bypass a
    URL-only cache. Supply ``key`` to partition those requests by a trusted
    identity; returning ``None`` bypasses caching for that request.
    """

    if max_age < 0:
        raise ValueError("max_age must be >= 0")
    if max_entries < 1:
        raise ValueError("max_entries must be >= 1")
    if max_bytes < 1:
        raise ValueError("max_bytes must be >= 1")
    if private and key is None:
        raise ValueError("private caches require an explicit identity key")

    store: dict[_CacheKey, _Entry] = {}
    total_bytes = 0
    # An application-only partition key cannot be represented to downstream
    # shared caches. Mark every keyed response private even when the caller did
    # not repeat ``private=True``.
    directive = f"{'private' if private or key is not None else 'public'}, max-age={max_age}"

    def remove(cache_key: _CacheKey) -> None:
        nonlocal total_bytes
        entry = store.pop(cache_key, None)
        if entry is not None:
            total_bytes -= entry.size

    def request_key(c: Context) -> _CacheKey | None:
        url_key = c.req.url.pathname + c.req.url.search
        if key is None:
            if any(
                c.req.header(name) is not None
                for name in ("authorization", "proxy-authorization", "cookie")
            ):
                return None
            return None, url_key

        partition = key(c)
        if partition is None:
            return None
        if not isinstance(partition, str) or not partition:
            raise TypeError("cache key must return a non-empty string or None")
        return partition, url_key

    async def cache_middleware(c: Context, next_: Next) -> None:
        nonlocal total_bytes
        if c.req.method != "GET":
            await next_()
            return
        cache_key = request_key(c)
        if cache_key is None:
            await next_()
            return

        now = time.monotonic()
        entry = store.get(cache_key)
        if entry is not None:
            if entry.expires_at > now:
                # A hit becomes the most-recently-used entry.
                del store[cache_key]
                store[cache_key] = entry
                response = Response(entry.body, entry.status, headers=entry.headers)
                response.headers.set("age", str(int(now - entry.stored_at)))
                c.res = response
                return
            remove(cache_key)

        await next_()
        res = c.res
        if res is None or res.status != 200:
            return
        response_body = res.body
        if not (response_body is None or isinstance(response_body, bytes)):
            return  # streams are not buffered just to cache them
        assert response_body is None or isinstance(response_body, bytes)
        if res.headers.get("set-cookie") is not None:
            return

        res.headers.set("cache-control", directive)
        header_pairs = res.headers.raw()
        size = _entry_size(header_pairs, response_body)
        if size > max_bytes:
            return

        while store and (len(store) >= max_entries or total_bytes + size > max_bytes):
            remove(next(iter(store)))
        store[cache_key] = _Entry(
            expires_at=now + max_age,
            stored_at=now,
            status=res.status,
            headers=header_pairs,
            body=response_body,
            size=size,
        )
        total_bytes += size

    return cache_middleware
