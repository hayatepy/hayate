"""Probe Hayate's wire-level Lambda Runtime API streaming from a container."""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from time import monotonic
from typing import Any

_DELIMITER = b"\0" * 8
_EXPECTED_METADATA = {
    "statusCode": 202,
    "headers": {
        "content-type": "text/plain;charset=utf-8",
        "x-stream": "hayate",
    },
    "multiValueHeaders": {"x-value": ["one", "two"]},
    "cookies": ["sid=streamed; Path=/; Secure; HttpOnly"],
}
_EVENT = {
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
            "method": "GET",
            "path": "/stream",
            "protocol": "HTTP/1.1",
            "sourceIp": "127.0.0.1",
        },
    },
    "isBase64Encoded": False,
}


class RuntimeAPIServer(HTTPServer):
    failure: Exception | None = None


class RuntimeAPIHandler(BaseHTTPRequestHandler):
    server: RuntimeAPIServer

    def log_message(self, format: str, *args: Any) -> None:
        pass

    def _complete(self) -> None:
        threading.Thread(target=self.server.shutdown, daemon=True).start()

    def do_GET(self) -> None:
        if self.path != "/2018-06-01/runtime/invocation/next":
            self.send_error(404)
            return
        payload = json.dumps(_EVENT, separators=(",", ":")).encode()
        self.send_response(200)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(payload)))
        self.send_header("Lambda-Runtime-Aws-Request-Id", "stream-request")
        self.send_header("Lambda-Runtime-Trace-Id", "Root=stream-trace")
        self.end_headers()
        self.wfile.write(payload)

    def do_POST(self) -> None:
        try:
            self._validate_stream()
        except Exception as error:
            self.server.failure = error
            self.send_error(500, explain=str(error))
        else:
            self.send_response(202)
            self.send_header("content-length", "0")
            self.end_headers()
        finally:
            self._complete()

    def _validate_stream(self) -> None:
        expected_path = "/2018-06-01/runtime/invocation/stream-request/response"
        assert self.path == expected_path, self.path
        assert self.headers["Content-Type"] == (
            "application/vnd.awslambda.http-integration-response"
        )
        assert self.headers["Lambda-Runtime-Function-Response-Mode"] == "streaming"
        assert self.headers["Transfer-Encoding"] == "chunked"
        assert self.headers["Trailer"] == (
            "Lambda-Runtime-Function-Error-Type, Lambda-Runtime-Function-Error-Body"
        )

        chunks: list[tuple[float, bytes]] = []
        while True:
            size_line = self.rfile.readline()
            assert size_line.endswith(b"\r\n"), size_line
            size = int(size_line.removesuffix(b"\r\n"), 16)
            if size == 0:
                assert self.rfile.readline() == b"\r\n"
                break
            payload = self.rfile.read(size)
            chunks.append((monotonic(), payload))
            assert self.rfile.read(2) == b"\r\n"

        assert len(chunks) == 3, chunks
        metadata_payload, delimiter, trailing = chunks[0][1].partition(_DELIMITER)
        assert delimiter == _DELIMITER
        assert trailing == b""
        assert len(chunks[0][1]) <= 16 * 1024
        assert json.loads(metadata_payload) == _EXPECTED_METADATA
        assert chunks[1][1] == b"first\n"
        assert chunks[2][1] == b"second\n"
        delay = chunks[2][0] - chunks[1][0]
        assert delay >= 0.35, f"body chunks were buffered together ({delay:.3f}s apart)"
        print(f"Runtime API observed the first chunk {delay:.3f}s before the second", flush=True)


def main() -> int:
    server = RuntimeAPIServer(("0.0.0.0", 9001), RuntimeAPIHandler)
    print("Runtime API probe ready", flush=True)
    server.serve_forever()
    server.server_close()
    if server.failure is not None:
        raise server.failure
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
