"""Invoke and validate the packaged Hayate Lambda handler through the RIE."""

from __future__ import annotations

import base64
import json
import sys
import urllib.error
import urllib.request
from typing import Any


def invoke(endpoint: str, event: dict[str, Any]) -> dict[str, Any]:
    request = urllib.request.Request(
        endpoint,
        data=json.dumps(event, separators=(",", ":")).encode(),
        headers={"content-type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            payload = response.read()
    except urllib.error.HTTPError as error:
        payload = error.read()
        raise AssertionError(
            f"Lambda RIE invocation failed with {error.code}: {payload.decode(errors='replace')}"
        ) from error
    value = json.loads(payload)
    if not isinstance(value, dict):
        raise AssertionError(f"Lambda handler returned {type(value).__name__}, expected object")
    return value


def event(
    *,
    method: str = "GET",
    path: str = "/",
    query: str = "",
    headers: dict[str, str] | None = None,
    cookies: list[str] | None = None,
    body: str | None = None,
) -> dict[str, Any]:
    value: dict[str, Any] = {
        "version": "2.0",
        "routeKey": "$default",
        "rawPath": path,
        "rawQueryString": query,
        "headers": {
            "host": "function.example",
            "x-forwarded-proto": "http",
            **(headers or {}),
        },
        "requestContext": {
            "domainName": "function.example",
            "http": {
                "method": method,
                "path": path,
                "protocol": "HTTP/1.1",
                "sourceIp": "127.0.0.1",
            },
        },
        "isBase64Encoded": False,
    }
    if cookies is not None:
        value["cookies"] = cookies
    if body is not None:
        value["body"] = body
    return value


def main() -> int:
    if len(sys.argv) != 2:
        raise SystemExit("usage: check_lambda_runtime.py INVOCATION_ENDPOINT")
    endpoint = sys.argv[1]

    inspected = invoke(
        endpoint,
        event(
            method="POST",
            path="/inspect/abc",
            query="q=portable",
            cookies=["session=s-1", "theme=light"],
            body='{"ok":true}',
            headers={"content-type": "application/json"},
        ),
    )
    assert inspected["statusCode"] == 201
    assert inspected["isBase64Encoded"] is False
    assert json.loads(inspected["body"]) == {
        "method": "POST",
        "item_id": "abc",
        "query": "portable",
        "session": "s-1",
        "scheme": "http:",
        "body": {"ok": True},
    }

    cookies = invoke(endpoint, event(path="/cookies"))
    assert cookies["statusCode"] == 200
    assert cookies["body"] == "cookies"
    assert len(cookies["cookies"]) == 2
    assert cookies["cookies"][0].startswith("sid=abc")
    assert "set-cookie" not in cookies["headers"]

    binary = invoke(endpoint, event(path="/binary"))
    assert binary["statusCode"] == 200
    assert binary["isBase64Encoded"] is True
    assert base64.b64decode(binary["body"]) == b"\x00\xff"

    missing = invoke(endpoint, event(path="/missing"))
    assert missing["statusCode"] == 404
    assert missing["isBase64Encoded"] is False
    problem = json.loads(missing["body"])
    assert problem["status"] == 404
    assert problem["title"] == "Not Found"
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
