"""Static file serving with conditional requests and Range support.

Scoped-middleware form, mirroring Hono's ``serveStatic``:

    app.use("/assets/*", static_files(root="public", strip_prefix="/assets"))

Files are read fully into memory (via a worker thread); this targets
app assets, not bulk downloads — put a CDN in front for those. Implements
RFC 9110 conditional requests (ETag / If-None-Match -> 304) and single
byte ranges (§14: 206 / 416); multiple ranges are ignored, which the RFC
always permits.
"""

from __future__ import annotations

import asyncio
import mimetypes
from pathlib import Path
from typing import Literal
from urllib.parse import unquote

from ..context import Context, Middleware, Next
from ..exceptions import problem
from ..headers import Headers
from ..response import Response
from ._internal import etag_matches

# _parse_range outcome for a syntactically valid but unsatisfiable range.
_UNSATISFIABLE: Literal["unsatisfiable"] = "unsatisfiable"


def _parse_range(header: str, size: int) -> tuple[int, int] | Literal["unsatisfiable"] | None:
    """Parse a single-range ``Range`` header.

    Returns an inclusive ``(start, end)``, ``_UNSATISFIABLE`` (-> 416),
    or ``None`` to ignore the header (invalid syntax or multiple ranges
    — ignoring is always allowed by RFC 9110).
    """
    if not header.startswith("bytes="):
        return None
    spec = header[6:].strip()
    if "," in spec:
        return None
    start_text, separator, end_text = spec.partition("-")
    if not separator:
        return None
    if start_text == "":
        if not end_text.isdigit():
            return None
        suffix = int(end_text)
        if suffix == 0 or size == 0:
            return _UNSATISFIABLE
        return (max(0, size - suffix), size - 1)
    if not start_text.isdigit():
        return None
    start = int(start_text)
    if start >= size:
        return _UNSATISFIABLE
    if end_text == "":
        return (start, size - 1)
    if not end_text.isdigit():
        return None
    end = min(int(end_text), size - 1)
    if end < start:
        return None
    return (start, end)


def _read_slice(path: Path, start: int, end: int) -> bytes:
    with path.open("rb") as file:
        file.seek(start)
        return file.read(end - start + 1)


async def _serve(c: Context, path: Path) -> Response:
    stat = await asyncio.to_thread(path.stat)
    tag = f'W/"{stat.st_mtime_ns:x}-{stat.st_size:x}"'
    headers = Headers()
    headers.set("accept-ranges", "bytes")
    headers.set("etag", tag)
    content_type, _ = mimetypes.guess_type(path.name)
    if content_type is not None:
        headers.set("content-type", content_type)

    if_none_match = c.req.header("if-none-match")
    if if_none_match is not None and etag_matches(if_none_match, tag):
        return Response(None, 304, headers=headers)

    size = stat.st_size
    range_header = c.req.header("range")
    if range_header is not None:
        parsed = _parse_range(range_header, size)
        if parsed == _UNSATISFIABLE:
            headers.set("content-range", f"bytes */{size}")
            return problem(416, headers=headers)
        if parsed is not None:
            start, end = parsed
            data = await asyncio.to_thread(_read_slice, path, start, end)
            headers.set("content-range", f"bytes {start}-{end}/{size}")
            return Response(data, 206, headers=headers)

    data = await asyncio.to_thread(path.read_bytes)
    return Response(data, 200, headers=headers)


def static_files(
    *,
    root: str | Path,
    strip_prefix: str = "",
    index: str = "index.html",
) -> Middleware:
    """Serve files from a directory: single ``Range``, 304 revalidation, traversal-safe."""

    root_path = Path(root).resolve()

    async def static_files_middleware(c: Context, next_: Next) -> None:
        if c.req.method not in ("GET", "HEAD"):
            await next_()
            return
        pathname = c.req.url.pathname
        if strip_prefix and pathname.startswith(strip_prefix):
            pathname = pathname[len(strip_prefix) :]
        relative = unquote(pathname, errors="replace").lstrip("/")
        if "\x00" in relative:
            await next_()
            return
        candidate = (root_path / relative).resolve() if relative else root_path
        # Path traversal guard: resolved target must stay under root.
        if not candidate.is_relative_to(root_path):
            await next_()
            return
        if candidate.is_dir():
            candidate = candidate / index
        if not candidate.is_file():
            await next_()
            return
        c.res = await _serve(c, candidate)

    return static_files_middleware
