"""AWS Lambda adapters (Function URLs / API Gateway HTTP API, payload v2.0).

    from hayate.adapters.aws import to_lambda
    from app import app

    handler = to_lambda(app)

``to_lambda`` targets the managed Python runtime's buffered handler contract.
``run_lambda_streaming`` is a separately deployed custom-runtime loop for
incremental responses; managed Python does not expose Lambda's streaming
Runtime API itself.
"""

from __future__ import annotations

import asyncio
import base64
import http.client
import json
import os
from collections.abc import AsyncIterable, Mapping
from typing import TYPE_CHECKING, Any, Never

from ..headers import Headers
from ..request import Request

if TYPE_CHECKING:
    from collections.abc import Callable

    from ..app import Hayate
    from ..response import Response

_TEXT_EXACT = {
    "application/json",
    "application/javascript",
    "application/xml",
    "application/manifest+json",
    "image/svg+xml",
}
_RUNTIME_API_VERSION = "2018-06-01"
_STREAMING_CONTENT_TYPE = "application/vnd.awslambda.http-integration-response"
_STREAMING_DELIMITER = b"\0" * 8
_MAX_STREAMING_PRELUDE = 16 * 1024
_ERROR_TRAILER = "Lambda-Runtime-Function-Error-Type, Lambda-Runtime-Function-Error-Body"


class _StreamingResponseStartedError(RuntimeError):
    """The invocation error endpoint is no longer legal for this response."""


def _is_textual(content_type: str) -> bool:
    base = content_type.partition(";")[0].strip().lower()
    return (
        base.startswith("text/")
        or base in _TEXT_EXACT
        or base.endswith("+json")
        or base.endswith("+xml")
    )


def _payload_v2_http(event: Mapping[str, Any]) -> Mapping[str, Any]:
    if event.get("version") != "2.0":
        raise ValueError(
            "hayate's Lambda adapter requires an API Gateway HTTP API or "
            "Function URL payload in format version 2.0"
        )
    request_context = event.get("requestContext")
    if not isinstance(request_context, Mapping):
        raise ValueError("Lambda payload v2.0 is missing requestContext")
    http = request_context.get("http")
    if not isinstance(http, Mapping):
        raise ValueError("Lambda payload v2.0 is missing requestContext.http")
    return http


def _request_from_event(event: dict[str, Any]) -> Request:
    http = _payload_v2_http(event)
    method = http.get("method", "GET")
    path = event.get("rawPath") or "/"
    query = event.get("rawQueryString") or ""
    raw_headers = event.get("headers")
    if raw_headers is not None and not isinstance(raw_headers, Mapping):
        raise ValueError("Lambda payload v2.0 headers must be an object")
    header_map = raw_headers or {}
    pairs = list(header_map.items())
    request_cookies = event.get("cookies")
    if request_cookies:
        pairs.append(("cookie", "; ".join(request_cookies)))

    request_headers = Headers(pairs, guard="immutable")
    request_context = event["requestContext"]
    host = request_headers.get("host") or request_context.get("domainName", "lambda")
    scheme = (request_headers.get("x-forwarded-proto") or "https").lower()
    if scheme not in ("http", "https"):
        scheme = "https"
    target = f"{scheme}://{host}{path}"
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

    return Request(target, method=method, headers=request_headers, body=body)


def _response_metadata(response: Response, *, multi_value: bool = False) -> dict[str, Any]:
    headers: dict[str, str] = {}
    multi_value_headers: dict[str, list[str]] = {}
    set_cookies: list[str] = []
    for name, value in response._header_pairs_for_adapter():
        if name == "set-cookie":
            set_cookies.append(value)
        elif name in headers:
            previous = headers.pop(name)
            if multi_value:
                multi_value_headers[name] = [previous, value]
            else:
                headers[name] = f"{previous}, {value}"
        elif name in multi_value_headers:
            multi_value_headers[name].append(value)
        else:
            headers[name] = value

    metadata: dict[str, Any] = {"statusCode": response.status, "headers": headers}
    if multi_value_headers:
        metadata["multiValueHeaders"] = multi_value_headers
    if set_cookies:
        metadata["cookies"] = set_cookies
    return metadata


async def _handle(app: Hayate, event: dict[str, Any]) -> dict[str, Any]:
    request = _request_from_event(event)
    response = await app.fetch(request)
    background = response._background
    if background is not None:
        await background._drain()

    payload = response.body
    if payload is not None and not isinstance(payload, bytes):
        payload = await response.bytes()

    result = _response_metadata(response)
    if payload is None:
        result["body"] = ""
        result["isBase64Encoded"] = False
    else:
        content_type = response.headers.get("content-type") or ""
        if response.headers.has("content-encoding") or not _is_textual(content_type):
            result["body"] = base64.b64encode(payload).decode("ascii")
            result["isBase64Encoded"] = True
        else:
            try:
                result["body"] = payload.decode("utf-8")
                result["isBase64Encoded"] = False
            except UnicodeDecodeError:
                result["body"] = base64.b64encode(payload).decode("ascii")
                result["isBase64Encoded"] = True
    return result


def _send_chunk(connection: http.client.HTTPConnection, payload: bytes) -> None:
    if not payload:
        return
    connection.send(f"{len(payload):X}\r\n".encode())
    connection.send(payload)
    connection.send(b"\r\n")


def _finish_chunks(
    connection: http.client.HTTPConnection,
    *,
    error_type: str | None = None,
    error_body: bytes | None = None,
) -> None:
    connection.send(b"0\r\n")
    if error_type is not None:
        connection.send(f"Lambda-Runtime-Function-Error-Type: {error_type}\r\n".encode())
    if error_body is not None:
        encoded = base64.b64encode(error_body).decode()
        connection.send(f"Lambda-Runtime-Function-Error-Body: {encoded}\r\n".encode())
    connection.send(b"\r\n")


async def _body_chunks(
    response: Response,
    *,
    method: str,
) -> AsyncIterable[bytes]:
    body = response.body
    body_allowed = response.status >= 200 and response.status not in (204, 304)
    if method == "HEAD" or not body_allowed or body is None:
        return
    if isinstance(body, bytes):
        if body:
            yield body
        return
    async for chunk in body:
        payload = bytes(chunk)
        if payload:
            yield payload


def _runtime_response_path(request_id: str) -> str:
    return f"/{_RUNTIME_API_VERSION}/runtime/invocation/{request_id}/response"


async def _post_streaming_response(
    runtime_api: str,
    request_id: str,
    response: Response,
    *,
    method: str,
) -> None:
    metadata = json.dumps(
        _response_metadata(response, multi_value=True),
        separators=(",", ":"),
    ).encode()
    prelude = metadata + _STREAMING_DELIMITER
    if len(prelude) > _MAX_STREAMING_PRELUDE:
        raise ValueError("Lambda streaming response metadata and delimiter exceed 16 KiB")

    connection = http.client.HTTPConnection(runtime_api)
    started = False
    try:
        connection.putrequest("POST", _runtime_response_path(request_id), skip_accept_encoding=True)
        connection.putheader("Content-Type", _STREAMING_CONTENT_TYPE)
        connection.putheader("Lambda-Runtime-Function-Response-Mode", "streaming")
        connection.putheader("Transfer-Encoding", "chunked")
        connection.putheader("Trailer", _ERROR_TRAILER)
        connection.endheaders()
        started = True

        _send_chunk(connection, prelude)
        try:
            async for chunk in _body_chunks(response, method=method):
                _send_chunk(connection, chunk)
        except Exception as error:
            error_body = json.dumps(
                {
                    "errorMessage": str(error),
                    "errorType": type(error).__name__,
                    "stackTrace": [],
                },
                separators=(",", ":"),
            ).encode()
            _finish_chunks(
                connection,
                error_type=f"Runtime.StreamError.{type(error).__name__}",
                error_body=error_body,
            )
        else:
            _finish_chunks(connection)

        runtime_response = connection.getresponse()
        runtime_payload = runtime_response.read()
        if not 200 <= runtime_response.status < 300:
            raise RuntimeError(
                f"Lambda Runtime API rejected streaming response with "
                f"{runtime_response.status}: {runtime_payload.decode(errors='replace')}"
            )
    except Exception as error:
        if started:
            raise _StreamingResponseStartedError(
                "Lambda streaming response failed after the invocation response began"
            ) from error
        raise
    finally:
        connection.close()


def _next_invocation(runtime_api: str) -> tuple[str, dict[str, Any], str]:
    connection = http.client.HTTPConnection(runtime_api)
    connection.request("GET", f"/{_RUNTIME_API_VERSION}/runtime/invocation/next")
    runtime_response = connection.getresponse()
    payload = runtime_response.read()
    if runtime_response.status != 200:
        connection.close()
        raise RuntimeError(
            f"Lambda Runtime API next invocation failed with "
            f"{runtime_response.status}: {payload.decode(errors='replace')}"
        )
    request_id = runtime_response.getheader("Lambda-Runtime-Aws-Request-Id")
    trace_id = runtime_response.getheader("Lambda-Runtime-Trace-Id") or ""
    connection.close()
    if not request_id:
        raise RuntimeError("Lambda Runtime API invocation is missing a request id")
    event = json.loads(payload)
    if not isinstance(event, dict):
        raise ValueError("Lambda Runtime API HTTP event must be a JSON object")
    return request_id, event, trace_id


def _post_invocation_error(runtime_api: str, request_id: str, error: Exception) -> None:
    payload = json.dumps(
        {
            "errorMessage": str(error),
            "errorType": type(error).__name__,
            "stackTrace": [],
        },
        separators=(",", ":"),
    ).encode()
    connection = http.client.HTTPConnection(runtime_api)
    connection.request(
        "POST",
        f"/{_RUNTIME_API_VERSION}/runtime/invocation/{request_id}/error",
        body=payload,
        headers={
            "content-type": "application/json",
            "Lambda-Runtime-Function-Error-Type": f"Runtime.{type(error).__name__}",
        },
    )
    runtime_response = connection.getresponse()
    runtime_payload = runtime_response.read()
    connection.close()
    if not 200 <= runtime_response.status < 300:
        raise RuntimeError(
            f"Lambda Runtime API rejected invocation error with "
            f"{runtime_response.status}: {runtime_payload.decode(errors='replace')}"
        ) from error


async def _streaming_runtime_loop(app: Hayate, runtime_api: str) -> Never:
    while True:
        request_id, event, trace_id = _next_invocation(runtime_api)
        if trace_id:
            os.environ["_X_AMZN_TRACE_ID"] = trace_id
        try:
            request = _request_from_event(event)
            response = await app.fetch(request)
            await _post_streaming_response(
                runtime_api,
                request_id,
                response,
                method=request.method,
            )
            background = response._background
            if background is not None:
                await background._drain()
        except _StreamingResponseStartedError:
            raise
        except Exception as error:
            _post_invocation_error(runtime_api, request_id, error)


def to_lambda(app: Hayate) -> Callable[[dict[str, Any], Any], dict[str, Any]]:
    """Build a synchronous Lambda handler: ``handler = to_lambda(app)``."""

    def handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
        return asyncio.run(_handle(app, event))

    return handler


def run_lambda_streaming(app: Hayate, *, runtime_api: str | None = None) -> Never:
    """Run an opt-in custom Runtime API loop with incremental response bodies.

    AWS's managed Python runtime supports only the buffered handler returned by
    :func:`to_lambda`. A container or custom-runtime bootstrap calls this
    function instead and configures its Function URL or API Gateway integration
    for ``RESPONSE_STREAM``.
    """

    endpoint = runtime_api or os.environ.get("AWS_LAMBDA_RUNTIME_API")
    if not endpoint:
        raise RuntimeError("AWS_LAMBDA_RUNTIME_API is required for Lambda response streaming")
    asyncio.run(_streaming_runtime_loop(app, endpoint))
