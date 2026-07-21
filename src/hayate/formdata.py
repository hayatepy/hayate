"""``FormData`` and ``File``, plus form body parsers.

Covers ``application/x-www-form-urlencoded`` (URL Standard) and buffered
``multipart/form-data`` (RFC 7578). Streaming multipart parsing is out of
scope for v0.1 — bodies are read fully before parsing, so pair uploads
with the ``body_limit`` middleware.
"""

from __future__ import annotations

from collections.abc import Iterator


class File:
    """Minimal ``File`` (File API naming: ``name`` / ``type`` / ``size``)."""

    __slots__ = ("_data", "name", "type")

    def __init__(self, data: bytes, *, name: str, type: str = "application/octet-stream") -> None:
        self._data = data
        self.name = name
        self.type = type

    @property
    def size(self) -> int:
        return len(self._data)

    async def bytes(self) -> bytes:
        return self._data

    async def text(self) -> str:
        return self._data.decode("utf-8", errors="replace")

    def __repr__(self) -> str:
        return f"File(name={self.name!r}, type={self.type!r}, size={self.size})"


class FormData:
    __slots__ = ("_pairs",)

    def __init__(self) -> None:
        self._pairs: list[tuple[str, str | File]] = []

    def append(self, name: str, value: str | File) -> None:
        self._pairs.append((name, value))

    def get(self, name: str) -> str | File | None:
        for n, v in self._pairs:
            if n == name:
                return v
        return None

    def get_all(self, name: str) -> list[str | File]:
        return [v for n, v in self._pairs if n == name]

    def has(self, name: str) -> bool:
        return any(n == name for n, _ in self._pairs)

    def __iter__(self) -> Iterator[tuple[str, str | File]]:
        return iter(list(self._pairs))

    def __len__(self) -> int:
        return len(self._pairs)

    def __repr__(self) -> str:
        return f"FormData({self._pairs!r})"


def parse_header_params(value: str) -> dict[str, str]:
    """Parse ``key=value`` parameters from a structured header value.

    Used for ``content-type`` (boundary) and ``content-disposition``
    (name, filename). Quoted strings have surrounding quotes removed and
    ``\\"`` / ``\\\\`` unescaped.
    """
    params: dict[str, str] = {}
    for part in value.split(";")[1:]:
        if "=" not in part:
            continue
        key, _, raw = part.partition("=")
        raw = raw.strip()
        if raw.startswith('"') and raw.endswith('"') and len(raw) >= 2:
            raw = raw[1:-1].replace('\\"', '"').replace("\\\\", "\\")
        params[key.strip().lower()] = raw
    return params


def parse_multipart(body: bytes, boundary: str) -> FormData:
    """Parse a buffered ``multipart/form-data`` body (RFC 7578)."""
    form = FormData()
    delimiter = b"--" + boundary.encode("latin-1")
    for section in body.split(delimiter)[1:]:
        if section.startswith(b"--"):
            break  # closing delimiter
        section = section.removeprefix(b"\r\n")
        head, sep, payload = section.partition(b"\r\n\r\n")
        if not sep:
            continue
        payload = payload.removesuffix(b"\r\n")
        headers: dict[str, str] = {}
        for line in head.split(b"\r\n"):
            name, _, value = line.decode("latin-1").partition(":")
            headers[name.strip().lower()] = value.strip()
        disposition = headers.get("content-disposition", "")
        if not disposition.lower().startswith("form-data"):
            continue
        params = parse_header_params(disposition)
        name = params.get("name")
        if name is None:
            continue
        filename = params.get("filename")
        if filename is not None:
            content_type = headers.get("content-type", "application/octet-stream")
            form.append(name, File(payload, name=filename, type=content_type))
        else:
            form.append(name, payload.decode("utf-8", errors="replace"))
    return form
