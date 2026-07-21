"""Fetch-compatible ``Request`` and the routed server-side view.

``Request`` carries only what the Fetch Standard defines: method, URL,
headers, body, and signal. Server-side routing context (path parameters,
query helpers) lives on ``HayateRequest`` — the object handlers receive
as ``c.req`` — so the standard object is never polluted.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterable, AsyncIterator, Iterable, Mapping
from typing import Any
from urllib.parse import unquote

from .abort import AbortSignal
from .body import Body, BodyInit
from .cookies import parse_cookies
from .formdata import FormData, parse_header_params, parse_multipart
from .headers import Headers
from .url import URL, parse_form_urlencoded


class _TeeSource:
    """Buffers an async byte stream so two readers can replay it (``clone()``)."""

    __slots__ = ("_chunks", "_done", "_lock", "_source")

    def __init__(self, source: AsyncIterable[bytes]) -> None:
        self._source = source.__aiter__()
        self._chunks: list[bytes] = []
        self._done = False
        self._lock = asyncio.Lock()

    async def _chunk_at(self, index: int) -> bytes | None:
        while True:
            if index < len(self._chunks):
                return self._chunks[index]
            if self._done:
                return None
            async with self._lock:
                if index < len(self._chunks) or self._done:
                    continue
                try:
                    chunk = await anext(self._source)
                except StopAsyncIteration:
                    self._done = True
                    return None
                self._chunks.append(chunk)

    def reader(self) -> AsyncIterator[bytes]:
        async def gen() -> AsyncIterator[bytes]:
            index = 0
            while True:
                chunk = await self._chunk_at(index)
                if chunk is None:
                    return
                yield chunk
                index += 1

        return gen()


class Request(Body):
    __slots__ = ("_signal", "headers", "method", "url")

    def __init__(
        self,
        url: str | URL,
        *,
        method: str = "GET",
        headers: Headers | Mapping[str, str] | Iterable[tuple[str, str]] | None = None,
        body: BodyInit = None,
        signal: AbortSignal | None = None,
    ) -> None:
        self.url = url if isinstance(url, URL) else URL(url)
        self.method = method.upper()
        # Request headers are immutable, per the Fetch guard semantics.
        # An already-immutable Headers can be shared instead of copied.
        if isinstance(headers, Headers) and headers._guard == "immutable":
            self.headers = headers
        else:
            self.headers = Headers(headers, guard="immutable")
        self._signal = signal
        self._init_body(body)

    @property
    def signal(self) -> AbortSignal:
        # Created lazily: most requests never observe their signal.
        if self._signal is None:
            self._signal = AbortSignal()
        return self._signal

    def clone(self) -> Request:
        if self.body_used:
            raise TypeError("cannot clone a Request whose body is already used")
        body: BodyInit
        if self._stream is not None:
            tee = _TeeSource(self._stream)
            self._stream = tee.reader()
            body = tee.reader()
        else:
            body = self._buffer
        return Request(
            self.url, method=self.method, headers=self.headers, body=body, signal=self.signal
        )

    async def form_data(self) -> FormData:
        content_type = self.headers.get("content-type") or ""
        base = content_type.partition(";")[0].strip().lower()
        if base == "application/x-www-form-urlencoded":
            data = await self.bytes()
            form = FormData()
            for name, value in parse_form_urlencoded(data.decode("utf-8", errors="replace")):
                form.append(name, value)
            return form
        if base == "multipart/form-data":
            boundary = parse_header_params(content_type).get("boundary")
            if not boundary:
                raise TypeError("multipart/form-data content-type without a boundary")
            return parse_multipart(await self.bytes(), boundary)
        raise TypeError(f"cannot parse body as form data (content-type: {content_type!r})")

    def __repr__(self) -> str:
        return f"Request({self.method} {self.url.href!r})"


class HayateRequest:
    """The routed request handed to handlers as ``c.req``.

    Wraps the standard ``Request`` (available as ``.raw``) and adds
    server-side context: route parameters and query helpers. The standard
    surface (method, url, headers, body readers) is delegated unchanged.
    Route parameter values are percent-decoded; raw values are available
    via the URLPattern result if ever needed.
    """

    __slots__ = ("_params", "raw")

    def __init__(self, raw: Request) -> None:
        self.raw = raw
        self._params: dict[str, str | None] = {}

    @property
    def method(self) -> str:
        return self.raw.method

    @property
    def url(self) -> URL:
        return self.raw.url

    @property
    def headers(self) -> Headers:
        return self.raw.headers

    @property
    def signal(self) -> AbortSignal:
        return self.raw.signal

    def header(self, name: str) -> str | None:
        return self.raw.headers.get(name)

    def param(self, name: str) -> str | None:
        value = self._params.get(name)
        return None if value is None else unquote(value, errors="replace")

    @property
    def params(self) -> dict[str, str | None]:
        return {
            name: (None if value is None else unquote(value, errors="replace"))
            for name, value in self._params.items()
        }

    @property
    def cookies(self) -> dict[str, str]:
        header = self.raw.headers.get("cookie")
        return {} if header is None else parse_cookies(header)

    def query(self, name: str) -> str | None:
        return self.raw.url.search_params.get(name)

    def queries(self, name: str) -> list[str]:
        return self.raw.url.search_params.get_all(name)

    async def bytes(self) -> bytes:
        return await self.raw.bytes()

    async def text(self) -> str:
        return await self.raw.text()

    async def json(self) -> Any:
        return await self.raw.json()

    async def form_data(self) -> FormData:
        return await self.raw.form_data()

    def __repr__(self) -> str:
        return f"HayateRequest({self.method} {self.url.href!r})"
