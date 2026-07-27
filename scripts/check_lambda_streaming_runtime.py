"""Validate native Lambda response streaming through the local RIE."""

from __future__ import annotations

import http.client
import json
import sys
import time
from typing import Any
from urllib.parse import urlsplit

_DELIMITER = b"\0" * 8


def event(*, method: str = "GET") -> dict[str, Any]:
    return {
        "version": "2.0",
        "routeKey": "$default",
        "rawPath": "/stream",
        "rawQueryString": "",
        "headers": {
            "host": "function.example",
            "x-forwarded-proto": "https",
        },
        "requestContext": {
            "domainName": "function.example",
            "http": {
                "method": method,
                "path": "/stream",
                "protocol": "HTTP/1.1",
                "sourceIp": "127.0.0.1",
            },
        },
        "isBase64Encoded": False,
    }


def invoke(endpoint: str, *, method: str) -> tuple[dict[str, Any], bytes, float]:
    target = urlsplit(endpoint)
    if target.scheme != "http" or not target.hostname or target.port is None:
        raise AssertionError(f"expected an explicit local HTTP endpoint, got {endpoint!r}")
    connection = http.client.HTTPConnection(target.hostname, target.port, timeout=20)
    started = time.monotonic()
    connection.request(
        "POST",
        target.path,
        body=json.dumps(event(method=method), separators=(",", ":")).encode(),
        headers={"content-type": "application/json"},
    )
    response = connection.getresponse()
    if response.status != 200:
        payload = response.read()
        raise AssertionError(
            f"Lambda RIE invocation failed with {response.status}: "
            f"{payload.decode(errors='replace')}"
        )

    prelude = bytearray()
    while not prelude.endswith(_DELIMITER):
        byte = response.read(1)
        if not byte:
            raise AssertionError("Lambda RIE response ended before the metadata delimiter")
        prelude.extend(byte)
        if len(prelude) > 16 * 1024:
            raise AssertionError("Lambda response metadata delimiter appeared after 16 KiB")
    metadata = json.loads(prelude.removesuffix(_DELIMITER))
    first = response.read(6)
    remainder = response.read()
    complete_at = time.monotonic() - started
    connection.close()
    return metadata, first + remainder, complete_at


def main() -> int:
    if len(sys.argv) != 2:
        raise SystemExit("usage: check_lambda_streaming_runtime.py INVOCATION_ENDPOINT")
    endpoint = sys.argv[1]

    metadata, payload, _ = invoke(endpoint, method="GET")
    expected_metadata = {
        "statusCode": 202,
        "headers": {
            "content-type": "text/plain;charset=utf-8",
            "x-stream": "hayate",
        },
        "multiValueHeaders": {"x-value": ["one", "two"]},
        "cookies": ["sid=streamed; Path=/; Secure; HttpOnly"],
    }
    assert metadata == expected_metadata, metadata
    assert payload == b"first\nsecond\n"

    head_metadata, head_payload, head_complete_at = invoke(endpoint, method="HEAD")
    assert head_metadata == metadata, head_metadata
    assert head_payload == b""
    assert head_complete_at < 0.35, (
        f"HEAD consumed the delayed response stream ({head_complete_at:.3f}s)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
