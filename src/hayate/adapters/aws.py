"""AWS Lambda adapter (Function URLs / API Gateway HTTP API, payload v2.0).

    from hayate.adapters.aws import to_lambda
    from app import app

    handler = to_lambda(app)

Each invocation runs the app on a fresh event loop — the standard
pattern for sync Lambda handlers. Response bodies are emitted as text
when the content-type is textual and there is no content-encoding;
otherwise they are base64-encoded. ``Set-Cookie`` values map to the
payload's ``cookies`` list so they are never comma-joined.
"""

from __future__ import annotations

import asyncio
import base64
from typing import TYPE_CHECKING, Any

from ..headers import Headers
from ..request import Request

if TYPE_CHECKING:
    from collections.abc import Callable

    from ..app import Hayate

_TEXT_EXACT = {
    "application/json",
    "application/javascript",
    "application/xml",
    "application/manifest+json",
    "image/svg+xml",
}


def _is_textual(content_type: str) -> bool:
    base = content_type.partition(";")[0].strip().lower()
    return (
        base.startswith("text/")
        or base in _TEXT_EXACT
        or base.endswith("+json")
        or base.endswith("+xml")
    )


async def _handle(app: Hayate, event: dict[str, Any]) -> dict[str, Any]:
    http = event["requestContext"]["http"]
    method = http.get("method", "GET")
    path = event.get("rawPath") or "/"
    query = event.get("rawQueryString") or ""
    header_map: dict[str, str] = event.get("headers") or {}
    pairs = list(header_map.items())
    request_cookies = event.get("cookies")
    if request_cookies:
        pairs.append(("cookie", "; ".join(request_cookies)))

    host = header_map.get("host") or event["requestContext"].get("domainName", "lambda")
    target = f"https://{host}{path}"
    if query:
        target += f"?{query}"

    raw_body = event.get("body")
    body: bytes | str | None
    if raw_body is None:
        body = None
    elif event.get("isBase64Encoded"):
        body = base64.b64decode(raw_body)
    else:
        body = raw_body

    request = Request(target, method=method, headers=Headers(pairs, guard="immutable"), body=body)
    response = await app.fetch(request)
    background = response._background
    if background is not None:
        await background._drain()

    payload = response.body
    if payload is not None and not isinstance(payload, bytes):
        payload = await response.bytes()

    headers: dict[str, str] = {}
    set_cookies: list[str] = []
    for name, value in response.headers.raw():
        if name == "set-cookie":
            set_cookies.append(value)
        elif name in headers:
            headers[name] = f"{headers[name]}, {value}"
        else:
            headers[name] = value

    result: dict[str, Any] = {"statusCode": response.status, "headers": headers}
    if set_cookies:
        result["cookies"] = set_cookies
    if payload is None:
        result["body"] = ""
        result["isBase64Encoded"] = False
    else:
        content_type = response.headers.get("content-type") or ""
        if response.headers.has("content-encoding") or not _is_textual(content_type):
            result["body"] = base64.b64encode(payload).decode("ascii")
            result["isBase64Encoded"] = True
        else:
            result["body"] = payload.decode("utf-8")
            result["isBase64Encoded"] = False
    return result


def to_lambda(app: Hayate) -> Callable[[dict[str, Any], Any], dict[str, Any]]:
    """Build a synchronous Lambda handler: ``handler = to_lambda(app)``."""

    def handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
        return asyncio.run(_handle(app, event))

    return handler
