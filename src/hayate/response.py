"""Fetch-compatible ``Response``.

Divergences from Fetch (documented):

- ``Response.json()`` exists only as the async body reader; Python cannot
  have a classmethod and an instance method share one name. The JSON
  response builder lives on the context (``c.json(...)``).
- ``clone()`` is not implemented in v0.1; middleware replaces responses
  by constructing new ones.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from .body import Body, BodyInit
from .headers import Headers

_REDIRECT_STATUSES = (301, 302, 303, 307, 308)
_EMPTY_HEADER_PAIRS: tuple[tuple[str, str], ...] = ()
_TEXT_HEADER_PAIRS = (("content-type", "text/plain;charset=utf-8"),)


class Response(Body):
    """Fetch ``Response``: status, headers, and a one-shot body.

    Adapters translate it to whatever each runtime speaks.
    """

    __slots__ = ("_background", "_header_pairs", "_headers", "_text_body", "status")

    def __init__(
        self,
        body: BodyInit = None,
        status: int = 200,
        headers: Headers | Mapping[str, str] | Iterable[tuple[str, str]] | None = None,
        *,
        _default_content_type: str | None = None,
    ) -> None:
        if not 100 <= status <= 599:
            raise ValueError(f"status must be in 100-599, got {status}")
        # Internal contract: an ExecutionContext with pending wait_until()
        # work, drained by the adapter (or app.request) after delivery.
        self._background: Any = None
        # Adapters that natively accept text can avoid bytes -> Uint8Array FFI.
        self._text_body = body if isinstance(body, str) else None
        self.status = status
        default_content_type = (
            _default_content_type
            if _default_content_type is not None
            else ("text/plain;charset=utf-8" if isinstance(body, str) else None)
        )
        if headers is None:
            self._headers: Headers | None = None
            if default_content_type is None:
                self._header_pairs = _EMPTY_HEADER_PAIRS
            elif default_content_type == "text/plain;charset=utf-8":
                self._header_pairs = _TEXT_HEADER_PAIRS
            else:
                self._header_pairs = (("content-type", default_content_type),)
        else:
            self._headers = Headers(headers)
            self._header_pairs = _EMPTY_HEADER_PAIRS
            if default_content_type is not None and not self._headers.has("content-type"):
                self._headers._append_trusted("content-type", default_content_type)
        if isinstance(body, str):
            self._init_text_body(body)
        else:
            self._init_body(body)

    @property
    def headers(self) -> Headers:
        headers = self._headers
        if headers is None:
            headers = Headers._from_trusted_pairs(list(self._header_pairs))
            self._headers = headers
            self._header_pairs = _EMPTY_HEADER_PAIRS
        return headers

    def _header_pairs_for_adapter(
        self,
    ) -> list[tuple[str, str]] | tuple[tuple[str, str], ...]:
        headers = self._headers
        return self._header_pairs if headers is None else headers._raw_for_adapter()

    @property
    def ok(self) -> bool:
        return 200 <= self.status < 300

    @classmethod
    def redirect(cls, location: str, status: int = 302) -> Response:
        if status not in _REDIRECT_STATUSES:
            raise ValueError(f"redirect status must be one of {_REDIRECT_STATUSES}, got {status}")
        return cls(None, status, headers=[("location", location)])

    def __repr__(self) -> str:
        return f"Response(status={self.status})"
