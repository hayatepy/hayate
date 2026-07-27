"""``FormData`` and ``File``, plus bounded form body parsers."""

from __future__ import annotations

import asyncio
import builtins
import re
import sys
from collections.abc import AsyncIterable, AsyncIterator, Iterator
from contextlib import suppress
from dataclasses import dataclass
from importlib import import_module
from typing import BinaryIO, cast


class FormDataError(ValueError):
    """Base class for malformed or resource-unsafe form bodies."""


class FormDataLimitError(FormDataError):
    """A configured form parsing resource limit was exceeded."""


@dataclass(frozen=True, slots=True)
class FormDataLimits:
    """Resource limits shared by buffered and streaming form parsers."""

    max_body_bytes: int = 32 * 1024 * 1024
    max_file_bytes: int = 32 * 1024 * 1024
    max_field_bytes: int = 1024 * 1024
    max_parts: int = 1000
    max_header_bytes: int = 16 * 1024
    file_memory_bytes: int = 1024 * 1024

    def __post_init__(self) -> None:
        for name in (
            "max_body_bytes",
            "max_file_bytes",
            "max_field_bytes",
            "max_parts",
            "max_header_bytes",
            "file_memory_bytes",
        ):
            value = getattr(self, name)
            if not isinstance(value, int) or isinstance(value, bool) or value < 0:
                raise ValueError(f"{name} must be a non-negative integer")
        if self.max_parts == 0:
            raise ValueError("max_parts must be greater than zero")
        if self.max_header_bytes == 0:
            raise ValueError("max_header_bytes must be greater than zero")
        if self.file_memory_bytes > self.max_file_bytes:
            raise ValueError("file_memory_bytes cannot exceed max_file_bytes")


DEFAULT_FORM_DATA_LIMITS = FormDataLimits()


class File:
    """Fetch-shaped uploaded file with optional native temporary-file storage."""

    __slots__ = ("_closed", "_data", "_file", "_lock", "_size", "name", "type")

    def __init__(self, data: bytes, *, name: str, type: str = "application/octet-stream") -> None:
        self._data: bytes | None = data
        self._file: BinaryIO | None = None
        self._size = len(data)
        self._closed = False
        self._lock = asyncio.Lock()
        self.name = name
        self.type = type

    @classmethod
    def _from_temporary(
        cls,
        file: BinaryIO,
        *,
        size: int,
        name: str,
        type: str,
    ) -> File:
        upload = cls.__new__(cls)
        upload._data = None
        upload._file = file
        upload._size = size
        upload._closed = False
        upload._lock = asyncio.Lock()
        upload.name = name
        upload.type = type
        return upload

    @property
    def size(self) -> int:
        return self._size

    @property
    def spooled(self) -> bool:
        """Whether this upload spilled from memory to a native temporary file."""
        return self._file is not None

    @property
    def closed(self) -> bool:
        return self._closed

    def _ensure_open(self) -> None:
        if self._closed:
            raise ValueError("uploaded file is closed")

    def _read_temporary(self) -> bytes:
        file = self._file
        assert file is not None
        position = file.tell()
        try:
            file.seek(0)
            return file.read()
        finally:
            file.seek(position)

    async def bytes(self) -> bytes:
        self._ensure_open()
        if self._data is not None:
            return self._data
        async with self._lock:
            self._ensure_open()
            return await asyncio.to_thread(self._read_temporary)

    async def text(self) -> str:
        return (await self.bytes()).decode("utf-8", errors="replace")

    async def stream(self, chunk_size: int = 64 * 1024) -> AsyncIterator[builtins.bytes]:
        """Yield upload bytes without materializing a spooled file."""
        if not isinstance(chunk_size, int) or isinstance(chunk_size, bool) or chunk_size <= 0:
            raise ValueError("chunk_size must be a positive integer")
        self._ensure_open()
        if self._data is not None:
            for offset in range(0, len(self._data), chunk_size):
                yield self._data[offset : offset + chunk_size]
            return

        async with self._lock:
            self._ensure_open()
            file = self._file
            assert file is not None
            await asyncio.to_thread(file.seek, 0)
            while True:
                chunk = cast(builtins.bytes, await asyncio.to_thread(file.read, chunk_size))
                if not chunk:
                    return
                yield chunk

    async def close(self) -> None:
        async with self._lock:
            if self._closed:
                return
            self._closed = True
            file, self._file = self._file, None
            self._data = None
            if file is not None:
                await asyncio.to_thread(file.close)

    def __repr__(self) -> str:
        return f"File(name={self.name!r}, type={self.type!r}, size={self.size})"

    def __del__(self) -> None:
        file = getattr(self, "_file", None)
        if file is not None:
            with suppress(Exception):
                file.close()


class FormData:
    """Fetch ``FormData``: ordered ``(name, value)`` pairs; values are ``str`` or ``File``."""

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

    async def close(self) -> None:
        """Close every temporary file held by this form."""
        for _, value in self._pairs:
            if isinstance(value, File):
                await value.close()

    async def __aenter__(self) -> FormData:
        return self

    async def __aexit__(self, *_exc: object) -> None:
        await self.close()

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


def _py_sections(body: bytes, delimiter: bytes) -> list[tuple[bytes, bytes]]:
    """Split a multipart body into (header block, payload) section pairs.

    Only the byte scanning lives here; all semantic parsing stays in
    ``parse_multipart`` so the accelerated splitter below cannot diverge
    in meaning — parity between the two splitters is pinned by tests.
    """
    sections: list[tuple[bytes, bytes]] = []
    for section in body.split(delimiter)[1:]:
        if section.startswith(b"--"):
            break  # closing delimiter
        section = section.removeprefix(b"\r\n")
        head, sep, payload = section.partition(b"\r\n\r\n")
        if not sep:
            continue
        sections.append((head, payload.removesuffix(b"\r\n")))
    return sections


try:  # Tier 2: SIMD boundary scanning, single-copy payloads (hayate-accel).
    _sections = import_module("hayate_accel").multipart_sections
except ImportError:
    _sections = _py_sections


_BOUNDARY = re.compile(r"^[0-9A-Za-z'()+_,./:=? -]{1,70}$")
_HEADER_NAME = re.compile(rb"^[!#$%&'*+\-.^_`|~0-9A-Za-z]+$")


def _boundary_bytes(boundary: str) -> bytes:
    if not _BOUNDARY.fullmatch(boundary) or boundary.endswith(" "):
        raise FormDataError("multipart boundary must be 1-70 valid ASCII characters")
    try:
        return boundary.encode("ascii")
    except UnicodeEncodeError:
        raise FormDataError("multipart boundary must contain only ASCII") from None


def _headers(head: bytes, limits: FormDataLimits) -> dict[str, str]:
    if len(head) > limits.max_header_bytes:
        raise FormDataLimitError("multipart part headers exceed max_header_bytes")
    headers: dict[str, str] = {}
    for line in head.split(b"\r\n"):
        if not line:
            continue
        if b":" not in line:
            raise FormDataError("multipart part contains a malformed header")
        name, value = line.split(b":", 1)
        if not _HEADER_NAME.fullmatch(name.strip()):
            raise FormDataError("multipart part contains an invalid header name")
        stripped_value = value.strip()
        if any((byte < 0x20 and byte != 0x09) or byte == 0x7F for byte in stripped_value):
            raise FormDataError("multipart part contains an invalid header value")
        decoded_name = name.decode("latin-1").strip().lower()
        headers[decoded_name] = stripped_value.decode("latin-1")
    return headers


def _part_metadata(headers: dict[str, str]) -> tuple[str, str | None, str] | None:
    disposition = headers.get("content-disposition", "")
    if not disposition.lower().startswith("form-data"):
        return None
    params = parse_header_params(disposition)
    name = params.get("name")
    if name is None:
        raise FormDataError("multipart form-data part is missing a name")
    filename = params.get("filename")
    content_type = headers.get("content-type", "application/octet-stream")
    return name, filename, content_type


def parse_multipart(
    body: bytes,
    boundary: str,
    limits: FormDataLimits = DEFAULT_FORM_DATA_LIMITS,
) -> FormData:
    """Parse an already-buffered ``multipart/form-data`` body (RFC 7578)."""
    boundary_bytes = _boundary_bytes(boundary)
    if len(body) > limits.max_body_bytes:
        raise FormDataLimitError("form body exceeds max_body_bytes")
    form = FormData()
    sections = _sections(body, b"--" + boundary_bytes)
    if len(sections) > limits.max_parts:
        raise FormDataLimitError("multipart body exceeds max_parts")
    for head, payload in sections:
        metadata = _part_metadata(_headers(head, limits))
        if metadata is None:
            continue
        name, filename, content_type = metadata
        if filename is not None:
            if len(payload) > limits.max_file_bytes:
                raise FormDataLimitError("multipart file exceeds max_file_bytes")
            form.append(name, File(payload, name=filename, type=content_type))
        else:
            if len(payload) > limits.max_field_bytes:
                raise FormDataLimitError("multipart field exceeds max_field_bytes")
            form.append(name, payload.decode("utf-8", errors="replace"))
    return form


class _ChunkReader:
    __slots__ = ("buffer", "done", "limits", "source", "total")

    def __init__(self, source: AsyncIterable[bytes], limits: FormDataLimits) -> None:
        self.source = source.__aiter__()
        self.limits = limits
        self.buffer = bytearray()
        self.total = 0
        self.done = False

    async def read(self) -> bool:
        if self.done:
            return False
        try:
            chunk = bytes(await anext(self.source))
        except StopAsyncIteration:
            self.done = True
            return False
        self.total += len(chunk)
        if self.total > self.limits.max_body_bytes:
            raise FormDataLimitError("form body exceeds max_body_bytes")
        self.buffer.extend(chunk)
        return True

    async def ensure(self, size: int) -> bool:
        while len(self.buffer) < size:
            if not await self.read():
                return False
        return True

    async def until(self, marker: bytes, limit: int, label: str) -> bytes:
        while True:
            index = self.buffer.find(marker)
            if index >= 0:
                if index > limit:
                    raise FormDataLimitError(f"{label} exceeds its configured limit")
                value = bytes(self.buffer[:index])
                del self.buffer[: index + len(marker)]
                return value
            if len(self.buffer) > limit:
                raise FormDataLimitError(f"{label} exceeds its configured limit")
            if not await self.read():
                raise FormDataError(f"multipart body ended before {label}")

    async def drain(self) -> None:
        self.buffer.clear()
        while await self.read():
            self.buffer.clear()


class _PartSink:
    __slots__ = (
        "_data",
        "_file",
        "_limit",
        "_limit_name",
        "_memory_limit",
        "_size",
        "_spool",
    )

    def __init__(
        self,
        *,
        limit: int,
        limit_name: str,
        memory_limit: int,
        spool: bool,
    ) -> None:
        self._data = bytearray()
        self._file: BinaryIO | None = None
        self._limit = limit
        self._limit_name = limit_name
        self._memory_limit = memory_limit
        self._size = 0
        self._spool = spool

    def write(self, data: bytes | bytearray) -> None:
        if not data:
            return
        self._size += len(data)
        if self._size > self._limit:
            raise FormDataLimitError(f"multipart part exceeds {self._limit_name}")
        if self._spool and self._file is None and len(self._data) + len(data) > self._memory_limit:
            # Keep tempfile and its transitive filesystem imports out of
            # Workers/Pyodide module initialization.
            from tempfile import TemporaryFile

            self._file = TemporaryFile("w+b")  # noqa: SIM115 - owned by File
            self._file.write(self._data)
            self._data.clear()
        if self._file is None:
            self._data.extend(data)
        else:
            self._file.write(data)

    def finish_field(self) -> str:
        assert self._file is None
        return bytes(self._data).decode("utf-8", errors="replace")

    def finish_file(self, *, name: str, type: str) -> File:
        if self._file is None:
            return File(bytes(self._data), name=name, type=type)
        self._file.flush()
        self._file.seek(0)
        file, self._file = self._file, None
        return File._from_temporary(file, size=self._size, name=name, type=type)

    def close(self) -> None:
        file, self._file = self._file, None
        if file is not None:
            file.close()


async def _consume_part(
    reader: _ChunkReader,
    delimiter: bytes,
    sink: _PartSink,
) -> bool:
    """Write one part payload and return whether the closing boundary was read."""
    tail = len(delimiter) - 1
    while True:
        index = reader.buffer.find(delimiter)
        if index >= 0:
            suffix_offset = index + len(delimiter)
            if not await reader.ensure(suffix_offset + 2):
                raise FormDataError("multipart body ended after a boundary")
            suffix = bytes(reader.buffer[suffix_offset : suffix_offset + 2])
            if suffix in (b"\r\n", b"--"):
                sink.write(reader.buffer[:index])
                del reader.buffer[: suffix_offset + 2]
                return suffix == b"--"
            # Boundary-shaped bytes inside a payload are ordinary content.
            sink.write(reader.buffer[: index + 1])
            del reader.buffer[: index + 1]
            continue
        flush = len(reader.buffer) - tail
        if flush > 0:
            sink.write(reader.buffer[:flush])
            del reader.buffer[:flush]
        if not await reader.read():
            raise FormDataError("multipart body ended before its closing boundary")


async def parse_multipart_stream(
    source: AsyncIterable[bytes],
    boundary: str,
    limits: FormDataLimits = DEFAULT_FORM_DATA_LIMITS,
    *,
    spool_files: bool | None = None,
) -> FormData:
    """Incrementally parse multipart input, spooling large native files to disk."""
    boundary_bytes = _boundary_bytes(boundary)
    reader = _ChunkReader(source, limits)
    first_boundary = b"--" + boundary_bytes
    await reader.until(first_boundary, limits.max_header_bytes, "multipart preamble")
    if not await reader.ensure(2):
        raise FormDataError("multipart body ended after its initial boundary")
    if bytes(reader.buffer[:2]) == b"--":
        del reader.buffer[:2]
        await reader.drain()
        return FormData()
    if bytes(reader.buffer[:2]) != b"\r\n":
        raise FormDataError("multipart initial boundary is malformed")
    del reader.buffer[:2]

    spool = sys.platform != "emscripten" if spool_files is None else spool_files
    form = FormData()
    delimiter = b"\r\n--" + boundary_bytes
    try:
        for _part in range(limits.max_parts):
            head = await reader.until(
                b"\r\n\r\n",
                limits.max_header_bytes,
                "multipart part headers",
            )
            metadata = _part_metadata(_headers(head, limits))
            filename = metadata[1] if metadata is not None else None
            sink = _PartSink(
                limit=(limits.max_file_bytes if filename is not None else limits.max_field_bytes),
                limit_name=("max_file_bytes" if filename is not None else "max_field_bytes"),
                memory_limit=limits.file_memory_bytes,
                spool=spool and filename is not None,
            )
            try:
                closing = await _consume_part(reader, delimiter, sink)
                if metadata is not None:
                    name, filename, content_type = metadata
                    if filename is None:
                        form.append(name, sink.finish_field())
                    else:
                        form.append(
                            name,
                            sink.finish_file(name=filename, type=content_type),
                        )
            finally:
                sink.close()
            if closing:
                await reader.drain()
                return form
        raise FormDataLimitError("multipart body exceeds max_parts")
    except BaseException:
        await form.close()
        raise
