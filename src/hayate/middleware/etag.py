"""ETag / If-None-Match middleware (RFC 9110 conditional requests)."""

from __future__ import annotations

import hashlib

from ..context import Context, Middleware, Next
from ..headers import Headers
from ..response import Response
from ._internal import etag_matches

# Headers a 304 should carry when present (RFC 9110 §15.4.5).
_KEEP_ON_304 = ("cache-control", "content-location", "date", "etag", "expires", "vary")


def etag(*, weak: bool = True) -> Middleware:
    async def etag_middleware(c: Context, next_: Next) -> None:
        await next_()
        res = c.res
        if res is None or res.status != 200 or c.req.method not in ("GET", "HEAD"):
            return
        tag = res.headers.get("etag")
        if tag is None:
            body = res.body
            if not isinstance(body, bytes):
                return  # streaming bodies are not buffered just to hash them
            # Content fingerprint only — not a security context.
            digest = hashlib.sha1(body, usedforsecurity=False).hexdigest()
            tag = f'W/"{digest}"' if weak else f'"{digest}"'
            res.headers.set("etag", tag)
        if_none_match = c.req.header("if-none-match")
        if if_none_match is not None and etag_matches(if_none_match, tag):
            headers = Headers()
            for name in _KEEP_ON_304:
                value = res.headers.get(name)
                if value is not None:
                    headers.set(name, value)
            c.res = Response(None, 304, headers=headers)

    return etag_middleware
