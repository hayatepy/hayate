"""Native Lambda custom-runtime response streaming."""

from __future__ import annotations

import base64
import json
from typing import Any

import pytest

from hayate import Hayate, Response
from hayate.adapters import aws


class FakeRuntimeResponse:
    def __init__(
        self,
        *,
        status: int = 202,
        body: bytes = b"",
        headers: dict[str, str] | None = None,
    ) -> None:
        self.status = status
        self._body = body
        self._headers = {name.lower(): value for name, value in (headers or {}).items()}

    def read(self) -> bytes:
        return self._body

    def getheader(self, name: str) -> str | None:
        return self._headers.get(name.lower())


class FakeRuntimeConnection:
    def __init__(self, response: FakeRuntimeResponse | None = None) -> None:
        self.response = response or FakeRuntimeResponse()
        self.method = ""
        self.path = ""
        self.headers: dict[str, str] = {}
        self.sent = bytearray()
        self.closed = False
        self.request_body: bytes | None = None

    def putrequest(self, method: str, path: str, **kwargs: Any) -> None:
        self.method = method
        self.path = path

    def putheader(self, name: str, value: str) -> None:
        self.headers[name.lower()] = value

    def endheaders(self) -> None:
        pass

    def send(self, payload: bytes) -> None:
        self.sent.extend(payload)

    def request(
        self,
        method: str,
        path: str,
        body: bytes | None = None,
        headers: dict[str, str] | None = None,
    ) -> None:
        self.method = method
        self.path = path
        self.request_body = body
        self.headers = {name.lower(): value for name, value in (headers or {}).items()}

    def getresponse(self) -> FakeRuntimeResponse:
        return self.response

    def close(self) -> None:
        self.closed = True


def _chunked_payload(payload: bytes) -> tuple[list[bytes], dict[str, str]]:
    chunks: list[bytes] = []
    position = 0
    while True:
        line_end = payload.index(b"\r\n", position)
        size = int(payload[position:line_end], 16)
        position = line_end + 2
        if size == 0:
            trailer_payload = payload[position:]
            assert trailer_payload.endswith(b"\r\n")
            trailers = {}
            for line in trailer_payload.removesuffix(b"\r\n").split(b"\r\n"):
                if line:
                    name, value = line.decode().split(": ", 1)
                    trailers[name.lower()] = value
            return chunks, trailers
        chunks.append(payload[position : position + size])
        position += size
        assert payload[position : position + 2] == b"\r\n"
        position += 2


async def test_streaming_response_uses_runtime_api_framing(monkeypatch):
    connection = FakeRuntimeConnection()
    monkeypatch.setattr(aws.http.client, "HTTPConnection", lambda endpoint: connection)

    async def body():
        yield b"first"
        yield b"second"

    response = Response(
        body(),
        201,
        headers=[
            ("content-type", "text/plain"),
            ("x-value", "one"),
            ("x-value", "two"),
            ("set-cookie", "sid=abc"),
            ("set-cookie", "theme=dark"),
        ],
    )
    await aws._post_streaming_response("runtime:9001", "request-1", response, method="GET")

    assert connection.method == "POST"
    assert connection.path == "/2018-06-01/runtime/invocation/request-1/response"
    assert connection.headers["content-type"] == (
        "application/vnd.awslambda.http-integration-response"
    )
    assert connection.headers["lambda-runtime-function-response-mode"] == "streaming"
    assert connection.headers["transfer-encoding"] == "chunked"
    assert connection.headers["trailer"] == (
        "Lambda-Runtime-Function-Error-Type, Lambda-Runtime-Function-Error-Body"
    )
    assert connection.closed

    chunks, trailers = _chunked_payload(bytes(connection.sent))
    metadata_payload, delimiter, trailing = chunks[0].partition(b"\0" * 8)
    assert delimiter == b"\0" * 8
    assert trailing == b""
    assert len(chunks[0]) <= 16 * 1024
    assert json.loads(metadata_payload) == {
        "statusCode": 201,
        "headers": {"content-type": "text/plain"},
        "multiValueHeaders": {"x-value": ["one", "two"]},
        "cookies": ["sid=abc", "theme=dark"],
    }
    assert chunks[1:] == [b"first", b"second"]
    assert trailers == {}


@pytest.mark.parametrize(("method", "status"), [("HEAD", 200), ("GET", 204), ("GET", 304)])
async def test_no_body_response_does_not_iterate_stream(monkeypatch, method, status):
    connection = FakeRuntimeConnection()
    monkeypatch.setattr(aws.http.client, "HTTPConnection", lambda endpoint: connection)
    iterated = False

    async def body():
        nonlocal iterated
        iterated = True
        yield b"must-not-be-sent"

    await aws._post_streaming_response(
        "runtime:9001",
        "request-2",
        Response(body(), status),
        method=method,
    )

    chunks, trailers = _chunked_payload(bytes(connection.sent))
    assert len(chunks) == 1
    assert chunks[0].endswith(b"\0" * 8)
    assert trailers == {}
    assert not iterated


async def test_midstream_error_uses_runtime_error_trailers(monkeypatch):
    connection = FakeRuntimeConnection()
    monkeypatch.setattr(aws.http.client, "HTTPConnection", lambda endpoint: connection)

    async def body():
        yield b"delivered"
        raise ValueError("stream failed")

    await aws._post_streaming_response(
        "runtime:9001",
        "request-3",
        Response(body()),
        method="GET",
    )

    chunks, trailers = _chunked_payload(bytes(connection.sent))
    assert chunks[1:] == [b"delivered"]
    assert trailers["lambda-runtime-function-error-type"] == "Runtime.StreamError.ValueError"
    error = json.loads(base64.b64decode(trailers["lambda-runtime-function-error-body"]))
    assert error == {
        "errorMessage": "stream failed",
        "errorType": "ValueError",
        "stackTrace": [],
    }


async def test_oversized_metadata_fails_before_response_starts(monkeypatch):
    def unexpected_connection(endpoint):
        raise AssertionError("Runtime API response must not start")

    monkeypatch.setattr(aws.http.client, "HTTPConnection", unexpected_connection)
    response = Response(b"body", headers={"x-large": "x" * (16 * 1024)})

    with pytest.raises(ValueError, match="exceed 16 KiB"):
        await aws._post_streaming_response(
            "runtime:9001",
            "request-4",
            response,
            method="GET",
        )


async def test_runtime_rejection_after_stream_start_closes_connection(monkeypatch):
    connection = FakeRuntimeConnection(FakeRuntimeResponse(status=500, body=b"runtime unavailable"))
    monkeypatch.setattr(aws.http.client, "HTTPConnection", lambda endpoint: connection)

    with pytest.raises(aws._StreamingResponseStartedError) as captured:
        await aws._post_streaming_response(
            "runtime:9001",
            "request-5",
            Response(b"body"),
            method="GET",
        )

    assert isinstance(captured.value.__cause__, RuntimeError)
    assert "runtime unavailable" in str(captured.value.__cause__)
    assert connection.closed


async def test_runtime_does_not_call_error_endpoint_after_response_started(monkeypatch):
    event = {
        "version": "2.0",
        "rawPath": "/",
        "headers": {"host": "fn.example"},
        "requestContext": {"http": {"method": "GET"}},
    }
    monkeypatch.setattr(
        aws,
        "_next_invocation",
        lambda endpoint: ("request-started", event, ""),
    )

    async def fail_after_start(*args, **kwargs):
        raise aws._StreamingResponseStartedError("started")

    def unexpected_error(*args, **kwargs):
        raise AssertionError("the invocation error endpoint is no longer legal")

    monkeypatch.setattr(aws, "_post_streaming_response", fail_after_start)
    monkeypatch.setattr(aws, "_post_invocation_error", unexpected_error)

    with pytest.raises(aws._StreamingResponseStartedError):
        await aws._streaming_runtime_loop(Hayate(), "runtime:9001")


def test_next_invocation_reads_runtime_headers(monkeypatch):
    event = {"version": "2.0", "requestContext": {"http": {"method": "GET"}}}
    connection = FakeRuntimeConnection(
        FakeRuntimeResponse(
            status=200,
            body=json.dumps(event).encode(),
            headers={
                "Lambda-Runtime-Aws-Request-Id": "request-5",
                "Lambda-Runtime-Trace-Id": "Root=trace",
            },
        )
    )
    monkeypatch.setattr(aws.http.client, "HTTPConnection", lambda endpoint: connection)

    assert aws._next_invocation("runtime:9001") == ("request-5", event, "Root=trace")
    assert connection.method == "GET"
    assert connection.path == "/2018-06-01/runtime/invocation/next"
    assert connection.closed


def test_invocation_error_uses_runtime_error_endpoint(monkeypatch):
    connection = FakeRuntimeConnection()
    monkeypatch.setattr(aws.http.client, "HTTPConnection", lambda endpoint: connection)

    aws._post_invocation_error("runtime:9001", "request-6", ValueError("bad event"))

    assert connection.method == "POST"
    assert connection.path == "/2018-06-01/runtime/invocation/request-6/error"
    assert connection.headers["lambda-runtime-function-error-type"] == "Runtime.ValueError"
    assert json.loads(connection.request_body or b"") == {
        "errorMessage": "bad event",
        "errorType": "ValueError",
        "stackTrace": [],
    }
    assert connection.closed


def test_public_streaming_runtime_requires_runtime_api(monkeypatch):
    monkeypatch.delenv("AWS_LAMBDA_RUNTIME_API", raising=False)

    with pytest.raises(RuntimeError, match="AWS_LAMBDA_RUNTIME_API is required"):
        aws.run_lambda_streaming(None)  # type: ignore[arg-type]
