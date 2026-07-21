"""HTTP errors and RFC 9457 Problem Details responses.

hayate does not invent an error JSON shape: every error response is an
``application/problem+json`` document per RFC 9457, produced either from
a raised ``HTTPException`` or by the framework defaults (404/405/500).
"""

from __future__ import annotations

import json as _json
from collections.abc import Iterable, Mapping
from http import HTTPStatus
from typing import Any

from .headers import Headers
from .response import Response


def problem(
    status: int,
    *,
    title: str | None = None,
    detail: str | None = None,
    type: str | None = None,
    instance: str | None = None,
    extensions: Mapping[str, Any] | None = None,
    headers: Headers | Mapping[str, str] | Iterable[tuple[str, str]] | None = None,
) -> Response:
    """Build an RFC 9457 ``application/problem+json`` response.

    Member names mirror the RFC ("type" defaults to "about:blank" by
    omission). ``extensions`` become extension members.
    """
    if title is None:
        try:
            title = HTTPStatus(status).phrase
        except ValueError:
            title = "Error"
    payload: dict[str, Any] = {"title": title, "status": status}
    if type is not None:
        payload["type"] = type
    if detail is not None:
        payload["detail"] = detail
    if instance is not None:
        payload["instance"] = instance
    if extensions:
        payload.update(extensions)
    merged = Headers(headers)
    merged.set("content-type", "application/problem+json")
    return Response(_json.dumps(payload), status, headers=merged)


class HTTPException(Exception):
    """Raise anywhere in a handler or middleware to produce an error response."""

    def __init__(
        self,
        status: int,
        *,
        title: str | None = None,
        detail: str | None = None,
        type: str | None = None,
        instance: str | None = None,
        headers: Headers | Mapping[str, str] | Iterable[tuple[str, str]] | None = None,
        extensions: Mapping[str, Any] | None = None,
    ) -> None:
        super().__init__(f"{status}{f' {title}' if title else ''}")
        self.status = status
        self.title = title
        self.detail = detail
        self.type = type
        self.instance = instance
        self.headers = Headers(headers)
        self.extensions = extensions

    def to_response(self) -> Response:
        return problem(
            self.status,
            title=self.title,
            detail=self.detail,
            type=self.type,
            instance=self.instance,
            extensions=self.extensions,
            headers=self.headers,
        )
