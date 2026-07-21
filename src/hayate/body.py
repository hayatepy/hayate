"""Shared body storage and consumption (the Fetch ``Body`` mixin).

A body is stored in one of two normalized forms: a ``bytes`` buffer or an
async byte stream. ``str`` input is encoded to UTF-8 at construction so
there is a single downstream representation.

Divergence from Fetch (documented): ``.body`` exposes the raw
representation (``None | bytes | AsyncIterable[bytes]``) instead of a
ReadableStream view — Python's idiom for a byte stream is the async
iterable itself. The one-shot consumption rule (``body_used``) applies to
the reader methods; iterating a stream body directly is an adapter-level
concern.
"""

from __future__ import annotations

import json as _json
from collections.abc import AsyncIterable
from typing import Any

type BodyInit = bytes | bytearray | str | AsyncIterable[bytes] | None


class Body:
    __slots__ = ("_buffer", "_stream", "_used")

    def _init_body(self, body: BodyInit) -> None:
        self._used = False
        self._buffer: bytes | None
        self._stream: AsyncIterable[bytes] | None
        if body is None:
            self._buffer = None
            self._stream = None
        elif isinstance(body, str):
            self._buffer = body.encode("utf-8")
            self._stream = None
        elif isinstance(body, bytes | bytearray):
            self._buffer = bytes(body)
            self._stream = None
        elif isinstance(body, AsyncIterable):
            self._buffer = None
            self._stream = body
        else:
            raise TypeError(
                "body must be None, bytes, str, or an async iterable of bytes, "
                f"got {type(body).__name__}"
            )

    @property
    def body(self) -> bytes | AsyncIterable[bytes] | None:
        """The raw body: ``None``, a ``bytes`` buffer, or an async byte stream."""
        return self._buffer if self._stream is None else self._stream

    @property
    def body_used(self) -> bool:
        return self._used

    def _mark_used(self) -> None:
        if self._used:
            raise TypeError("body already used")
        self._used = True

    async def bytes(self) -> bytes:
        """Read the whole body (Fetch ``bytes()``). One-shot."""
        self._mark_used()
        if self._stream is not None:
            chunks = [bytes(chunk) async for chunk in self._stream]
            self._buffer = b"".join(chunks)
            self._stream = None
        return self._buffer if self._buffer is not None else b""

    async def text(self) -> str:
        """UTF-8 decode per Fetch: strip a leading BOM, replace invalid bytes."""
        data = await self.bytes()
        return data.decode("utf-8", errors="replace").removeprefix("﻿")

    async def json(self) -> Any:
        return _json.loads(await self.text())
