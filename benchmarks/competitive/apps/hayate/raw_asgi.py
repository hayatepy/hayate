"""The common workload as a minimal ASGI transport ceiling.

This target runs in hayate's locked Uvicorn environment. It is not a fifth
framework: it isolates the maximum throughput available from the shared
Python transport before any framework adapts the ASGI scope to its API.
"""

from __future__ import annotations

import json
from typing import Any

_TEXT_HEADERS = [(b"content-type", b"text/plain; charset=utf-8")]
_JSON_HEADERS = [(b"content-type", b"application/json")]


async def app(scope: dict[str, Any], receive: Any, send: Any) -> None:
    method = scope["method"]
    path = scope["path"]

    if method == "GET" and path == "/text":
        await _respond(send, b"hello", _TEXT_HEADERS)
        return

    if method == "GET" and path.startswith("/items/"):
        item_id = path.removeprefix("/items/")
        body = _json_bytes({"id": item_id, "name": f"item-{item_id}"})
        await _respond(send, body, _JSON_HEADERS)
        return

    if method == "POST" and path == "/echo":
        payload = json.loads((await _request_body(receive)).decode())
        message = payload["message"]
        body = _json_bytes({"message": message, "length": len(message)})
        await _respond(send, body, _JSON_HEADERS)
        return

    if method == "GET" and path.startswith("/route"):
        route, separator, key = path[1:].partition("/")
        index = route.removeprefix("route")
        if separator and key and index.isdigit() and 0 <= int(index) < 64:
            await _respond(send, b"ok", _TEXT_HEADERS)
            return

    await send(
        {
            "type": "http.response.start",
            "status": 404,
            "headers": [(b"content-length", b"0")],
        }
    )
    await send({"type": "http.response.body", "body": b""})


async def _request_body(receive: Any) -> bytes:
    chunks: list[bytes] = []
    while True:
        message = await receive()
        if message["type"] != "http.request":
            continue
        chunks.append(message.get("body", b""))
        if not message.get("more_body", False):
            return b"".join(chunks)


async def _respond(
    send: Any,
    body: bytes,
    base_headers: list[tuple[bytes, bytes]],
) -> None:
    await send(
        {
            "type": "http.response.start",
            "status": 200,
            "headers": [*base_headers, (b"content-length", str(len(body)).encode())],
        }
    )
    await send({"type": "http.response.body", "body": body})


def _json_bytes(value: dict[str, Any]) -> bytes:
    return json.dumps(value, separators=(",", ":")).encode()
