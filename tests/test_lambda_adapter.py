"""AWS Lambda adapter (API Gateway HTTP API v2.0 / Function URL events).

The handler is synchronous (it owns its event loop), so these tests are
plain sync functions.
"""

import base64
import json
import logging

import pytest

from hayate import Context, Hayate
from hayate.adapters.aws import to_lambda
from hayate.middleware import current_request_id, logger, request_id


def make_event(
    *,
    method: str = "GET",
    path: str = "/",
    query: str = "",
    headers: dict[str, str] | None = None,
    cookies: list[str] | None = None,
    body: str | None = None,
    is_base64: bool = False,
) -> dict:
    event_headers = dict(headers or {})
    if not any(name.lower() == "host" for name in event_headers):
        event_headers["host"] = "fn.example"
    event = {
        "version": "2.0",
        "rawPath": path,
        "rawQueryString": query,
        "headers": event_headers,
        "requestContext": {"domainName": "fn.example", "http": {"method": method}},
    }
    if cookies is not None:
        event["cookies"] = cookies
    if body is not None:
        event["body"] = body
        event["isBase64Encoded"] = is_base64
    return event


def test_json_roundtrip():
    app = Hayate()

    @app.post("/items")
    async def create(c: Context):
        return c.json({"got": await c.req.json()}, 201)

    handler = to_lambda(app)
    result = handler(make_event(method="POST", path="/items", body='{"a": 1}'), None)
    assert result["statusCode"] == 201
    assert result["isBase64Encoded"] is False
    assert json.loads(result["body"]) == {"got": {"a": 1}}
    assert result["headers"]["content-type"] == "application/json"


def test_request_id_and_final_access_log_cross_lambda_adapter(caplog):
    app = Hayate()
    app.use(request_id())
    app.use(logger(structured=True))
    seen: list[str | None] = []

    @app.get("/")
    async def root(c: Context):
        seen.append(current_request_id())
        return c.text(c.get("request_id"))

    with caplog.at_level(logging.INFO, logger="hayate.request"):
        result = to_lambda(app)(
            make_event(headers={"x-request-id": "lambda-request-123"}),
            None,
        )
    assert result["body"] == "lambda-request-123"
    assert result["headers"]["x-request-id"] == "lambda-request-123"
    assert seen == ["lambda-request-123"]
    assert current_request_id() is None
    event = json.loads(
        next(record.getMessage() for record in caplog.records if record.name == "hayate.request")
    )
    assert (event["status"], event["request_id"]) == (200, "lambda-request-123")


def test_query_and_url():
    app = Hayate()

    @app.get("/q")
    async def q(c: Context):
        return c.json({"v": c.req.query("v"), "host": c.req.url.host})

    handler = to_lambda(app)
    result = handler(make_event(path="/q", query="v=1"), None)
    assert json.loads(result["body"]) == {"v": "1", "host": "fn.example"}


def test_forwarded_scheme_and_case_insensitive_host():
    app = Hayate()

    @app.get("/url")
    async def url(c: Context):
        return c.json({"url": str(c.req.url)})

    handler = to_lambda(app)
    result = handler(
        make_event(
            path="/url",
            query="a=1",
            headers={"Host": "custom.example", "X-Forwarded-Proto": "http"},
        ),
        None,
    )
    assert json.loads(result["body"]) == {"url": "http://custom.example/url?a=1"}


def test_binary_response_is_base64():
    app = Hayate()

    @app.get("/bin")
    async def binary(c: Context):
        return c.body(b"\x00\xff", headers={"content-type": "application/octet-stream"})

    handler = to_lambda(app)
    result = handler(make_event(path="/bin"), None)
    assert result["isBase64Encoded"] is True
    assert base64.b64decode(result["body"]) == b"\x00\xff"


def test_base64_request_body_is_decoded():
    app = Hayate()

    @app.post("/echo")
    async def echo(c: Context):
        return c.body(await c.req.bytes(), headers={"content-type": "application/octet-stream"})

    handler = to_lambda(app)
    payload = base64.b64encode(b"\x01\x02").decode()
    result = handler(make_event(method="POST", path="/echo", body=payload, is_base64=True), None)
    assert base64.b64decode(result["body"]) == b"\x01\x02"


def test_cookies_both_directions():
    app = Hayate()

    @app.get("/cookies")
    async def cookies(c: Context):
        c.set_cookie("sid", "abc", http_only=True)
        c.set_cookie("theme", "dark")
        return c.json(c.req.cookies)

    handler = to_lambda(app)
    result = handler(make_event(path="/cookies", cookies=["a=1", "b=2"]), None)
    assert json.loads(result["body"]) == {"a": "1", "b": "2"}
    assert len(result["cookies"]) == 2
    assert result["cookies"][0].startswith("sid=abc")
    assert "set-cookie" not in result["headers"]


def test_repeated_response_headers_are_comma_joined_for_payload_v2():
    app = Hayate()

    @app.get("/headers")
    async def headers(c: Context):
        return c.body(b"", headers=[("x-value", "one"), ("x-value", "two")])

    result = to_lambda(app)(make_event(path="/headers"), None)
    assert result["headers"]["x-value"] == "one, two"


def test_not_found_is_problem_json():
    app = Hayate()
    handler = to_lambda(app)
    result = handler(make_event(path="/missing"), None)
    assert result["statusCode"] == 404
    assert json.loads(result["body"])["title"] == "Not Found"


def test_invalid_utf8_text_response_falls_back_to_base64():
    app = Hayate()

    @app.get("/invalid-text")
    async def invalid_text(c: Context):
        return c.body(b"\xff", headers={"content-type": "text/plain"})

    result = to_lambda(app)(make_event(path="/invalid-text"), None)
    assert result["isBase64Encoded"] is True
    assert base64.b64decode(result["body"]) == b"\xff"


@pytest.mark.parametrize(
    ("event", "message"),
    [
        ({"version": "1.0"}, "payload in format version 2.0"),
        ({"version": "2.0"}, "missing requestContext"),
        ({"version": "2.0", "requestContext": {}}, "missing requestContext.http"),
    ],
)
def test_unsupported_or_malformed_event_is_actionable(event, message):
    with pytest.raises(ValueError, match=message):
        to_lambda(Hayate())(event, None)
