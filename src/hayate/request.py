"""Fetch-compatible ``Request`` and the routed server-side view.

``Request`` carries only what the Fetch Standard defines: method, URL,
headers, body, and signal. Server-side routing context (path parameters,
query helpers) lives on ``HayateRequest`` — the object handlers receive
as ``c.req`` — so the standard object is never polluted.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterable, AsyncIterator, Awaitable, Callable, Iterable, Mapping
from typing import Any
from urllib.parse import unquote

from .abort import AbortSignal
from .body import Body, BodyInit
from .cookies import parse_cookies
from .formdata import FormData, parse_header_params, parse_multipart
from .headers import Headers
from .url import URL, parse_form_urlencoded

_EMPTY_PARAMS: dict[str, str | None] = {}


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
    """Fetch ``Request``: URL, method, immutable headers, one-shot body, abort signal."""

    __slots__ = (
        "_header_loader",
        "_header_source",
        "_headers",
        "_routing_pathname",
        "_signal",
        "_signal_factory",
        "_signal_source",
        "_url",
        "_url_loader",
        "_url_source",
        "method",
    )

    def __init__(
        self,
        url: str | URL,
        *,
        method: str = "GET",
        headers: Headers | Mapping[str, str] | Iterable[tuple[str, str]] | None = None,
        body: BodyInit = None,
        signal: AbortSignal | None = None,
        _trusted_pathname: str | None = None,
        _header_source: Any = None,
        _header_loader: Callable[[Any], list[tuple[str, str]]] | None = None,
    ) -> None:
        if _trusted_pathname is None:
            self._url: URL | str = url if isinstance(url, URL) else URL(url)
            self._routing_pathname: str | None = None
            self.method = method.upper()
        else:
            if not isinstance(url, str):
                raise TypeError("a trusted platform URL must be a string")
            # The platform has already parsed and serialized this Fetch URL.
            # Keep its path for routing and defer our richer URL object until
            # application code actually asks for it.
            self._url = url
            self._routing_pathname = _trusted_pathname
            self.method = method
        self._url_loader: Callable[[Any], URL] | None = None
        self._url_source: Any = None
        self._headers: Headers | None
        self._header_source: Any
        self._header_loader: Callable[[Any], list[tuple[str, str]]] | None
        if _header_loader is not None:
            self._headers = None
            self._header_source = _header_source
            self._header_loader = _header_loader
        else:
            # Request headers are immutable, per the Fetch guard semantics.
            # An already-immutable Headers can be shared instead of copied.
            self._headers = (
                headers
                if isinstance(headers, Headers) and headers._guard == "immutable"
                else Headers(headers, guard="immutable")
            )
            self._header_source = None
            self._header_loader = None
        self._signal = signal
        self._signal_factory: Callable[[Any], AbortSignal] | None = None
        self._signal_source: Any = None
        self._init_body(body)

    @classmethod
    def _from_platform(
        cls,
        href: str,
        method: str,
        pathname: str,
        *,
        header_source: Any,
        header_loader: Callable[[Any], list[tuple[str, str]]],
        body: bytes | None,
        platform_body: AsyncIterable[bytes] | None,
        signal_source: Any,
        signal_factory: Callable[[Any], AbortSignal],
    ) -> Request:
        """Build from transport-validated components without reinitializing.

        Adapters have already normalized the URL, method, headers, body, and
        signal shapes. Assigning the final lazy state once avoids running the
        public constructor's validation branches and then overwriting its
        body/signal state with platform bridges.
        """
        request = cls.__new__(cls)
        request._url = href
        request._routing_pathname = pathname
        request._url_loader = None
        request._url_source = None
        request.method = method
        request._headers = None
        request._header_source = header_source
        request._header_loader = header_loader
        request._signal = None
        request._signal_factory = signal_factory
        request._signal_source = signal_source
        request._used = False
        request._platform = platform_body
        request._buffer = body
        request._stream = platform_body
        return request

    @property
    def url(self) -> URL:
        url = self._url
        loader = self._url_loader
        if loader is not None:
            url = loader(self._url_source)
            self._url_loader = None
            self._url_source = None
            self._url = url
        elif isinstance(url, str):
            url = URL(url) if self._routing_pathname is None else URL._from_trusted_href(url)
            self._url = url
        return url

    def _init_platform_url(self, source: Any, loader: Callable[[Any], URL]) -> None:
        """Adapter hook: construct the complete URL only on first access."""
        self._url_source = source
        self._url_loader = loader

    @property
    def headers(self) -> Headers:
        headers = self._headers
        if headers is None:
            loader = self._header_loader
            assert loader is not None
            headers = Headers._from_loader(
                self._header_source,
                loader,
                guard="immutable",
            )
            self._headers = headers
            self._header_source = None
            self._header_loader = None
        return headers

    def _pathname_for_routing(self) -> str:
        pathname = self._routing_pathname
        return self.url.pathname if pathname is None else pathname

    @property
    def signal(self) -> AbortSignal:
        # Created lazily: most requests never observe their signal. Adapters
        # may defer their platform bridge too, avoiding an FFI-lifecycle
        # object on the common request path.
        if self._signal is None:
            factory = self._signal_factory
            if factory is None:
                self._signal = AbortSignal()
            else:
                self._signal = factory(self._signal_source)
                self._signal_factory = None
                self._signal_source = None
        return self._signal

    def _init_platform_signal(self, source: Any, factory: Callable[[Any], AbortSignal]) -> None:
        """Adapter hook: create the platform AbortSignal bridge on access."""
        self._signal_factory = factory
        self._signal_source = source

    def _release_platform_signal(self) -> None:
        """Release an adapter signal bridge, if application code created it."""
        self._signal_factory = None
        self._signal_source = None
        signal = self._signal
        if signal is not None:
            release = getattr(signal, "release", None)
            if release is not None:
                release()

    def clone(self) -> Request:
        if self.body_used:
            raise TypeError("cannot clone a Request whose body is already used")
        body: BodyInit
        if self._stream is not None:
            tee = _TeeSource(self._stream)
            self._stream = tee.reader()
            self._platform = None
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

    __slots__ = ("_params", "_validated", "raw")

    def __init__(self, raw: Request) -> None:
        self.raw = raw
        # Routing replaces this reference for parameterized matches. The
        # empty mapping is immutable by convention and shared by static,
        # not-found, and method-mismatch requests.
        self._params = _EMPTY_PARAMS
        self._validated: dict[str, Any] | None = None

    @property
    def method(self) -> str:
        return self.raw.method

    @property
    def url(self) -> URL:
        return self.raw.url

    def _pathname_for_routing(self) -> str:
        return self.raw._pathname_for_routing()

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
        if value is None or "%" not in value:
            return value
        return unquote(value, errors="replace")

    @property
    def params(self) -> dict[str, str | None]:
        return {
            name: (value if value is None or "%" not in value else unquote(value, errors="replace"))
            for name, value in self._params.items()
        }

    @property
    def cookies(self) -> dict[str, str]:
        header = self.raw.headers.get("cookie")
        return {} if header is None else parse_cookies(header)

    def _set_valid(self, target: str, value: Any) -> None:
        if self._validated is None:
            self._validated = {}
        self._validated[target] = value

    def valid(self, target: str) -> Any:
        """Validated data stored by the ``validator`` middleware."""
        if self._validated is None or target not in self._validated:
            raise KeyError(f"no validated data for {target!r} — did the validator run?")
        return self._validated[target]

    def query(self, name: str) -> str | None:
        return self.raw.url.search_params.get(name)

    def queries(self, name: str) -> list[str]:
        return self.raw.url.search_params.get_all(name)

    def bytes(self) -> Awaitable[bytes]:
        return self.raw.bytes()

    def text(self) -> Awaitable[str]:
        return self.raw.text()

    def json(self) -> Awaitable[Any]:
        return self.raw.json()

    def form_data(self) -> Awaitable[FormData]:
        return self.raw.form_data()

    def __repr__(self) -> str:
        return f"HayateRequest({self.method} {self.url.href!r})"
