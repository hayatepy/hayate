"""Response compression: gzip everywhere, zstd on Python 3.14+ (PEP 784)."""

from __future__ import annotations

import gzip
import sys
from typing import TYPE_CHECKING, Any

from ..context import Context, Middleware, Next
from ..response import Response
from ._internal import append_vary

if TYPE_CHECKING:
    if sys.version_info >= (3, 14):
        from compression import zstd as _zstd
    else:
        _zstd: Any = None
else:
    try:  # Python 3.14+
        from compression import zstd as _zstd
    except ImportError:  # pragma: no cover - depends on the running Python
        _zstd = None

_COMPRESSIBLE_EXACT = {
    "application/json",
    "application/javascript",
    "application/xml",
    "application/manifest+json",
    "image/svg+xml",
}


def _compressible(content_type: str) -> bool:
    base = content_type.partition(";")[0].strip().lower()
    return (
        base.startswith("text/")
        or base in _COMPRESSIBLE_EXACT
        or base.endswith("+json")
        or base.endswith("+xml")
    )


def _accepted_encodings(header: str) -> set[str]:
    accepted: set[str] = set()
    for part in header.split(","):
        token = part.strip()
        if not token:
            continue
        name, _, params = token.partition(";")
        q = 1.0
        for param in params.split(";"):
            key, _, value = param.strip().partition("=")
            if key == "q":
                try:
                    q = float(value)
                except ValueError:
                    q = 0.0
        if q > 0:
            accepted.add(name.strip().lower())
    return accepted


def compress(*, min_size: int = 1024) -> Middleware:
    """Compress buffered response bodies when the client accepts it.

    Streaming bodies are passed through untouched in v0.1.
    """

    async def compress_middleware(c: Context, next_: Next) -> None:
        await next_()
        res = c.res
        if res is None or res.headers.has("content-encoding"):
            return
        body = res.body
        if not isinstance(body, bytes) or len(body) < min_size:
            return
        if not _compressible(res.headers.get("content-type") or ""):
            return
        accepted = _accepted_encodings(c.req.header("accept-encoding") or "")
        if _zstd is not None and "zstd" in accepted:
            data = _zstd.compress(body)
            encoding = "zstd"
        elif "gzip" in accepted:
            data = gzip.compress(body, mtime=0)
            encoding = "gzip"
        else:
            return
        if len(data) >= len(body):
            return
        replacement = Response(data, res.status, headers=res.headers)
        replacement.headers.set("content-encoding", encoding)
        replacement.headers.delete("content-length")
        append_vary(replacement.headers, "accept-encoding")
        c.res = replacement

    return compress_middleware
