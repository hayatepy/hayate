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

from .body import Body, BodyInit
from .headers import Headers

_REDIRECT_STATUSES = (301, 302, 303, 307, 308)


class Response(Body):
    __slots__ = ("headers", "status")

    def __init__(
        self,
        body: BodyInit = None,
        status: int = 200,
        headers: Headers | Mapping[str, str] | Iterable[tuple[str, str]] | None = None,
    ) -> None:
        if not 100 <= status <= 599:
            raise ValueError(f"status must be in 100-599, got {status}")
        self.status = status
        self.headers = Headers(headers)
        # Per Fetch: a text body implies text/plain;charset=UTF-8 unless set.
        if isinstance(body, str) and not self.headers.has("content-type"):
            self.headers.set("content-type", "text/plain;charset=utf-8")
        self._init_body(body)

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
