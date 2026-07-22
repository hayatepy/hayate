"""AWS Lambda adapter (API Gateway HTTP API v2.0 / Function URL events).

The handler is synchronous (it owns its event loop), so these tests are
plain sync functions.
"""

import base64
import json

from hayate import Context, Hayate
from hayate.adapters.aws import to_lambda


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
    event = {
        "version": "2.0",
        "rawPath": path,
        "rawQueryString": query,
        "headers": {"host": "fn.example", **(headers or {})},
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


def test_query_and_url():
    app = Hayate()

    @app.get("/q")
    async def q(c: Context):
        return c.json({"v": c.req.query("v"), "host": c.req.url.host})

    handler = to_lambda(app)
    result = handler(make_event(path="/q", query="v=1"), None)
    assert json.loads(result["body"]) == {"v": "1", "host": "fn.example"}


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


def test_not_found_is_problem_json():
    app = Hayate()
    handler = to_lambda(app)
    result = handler(make_event(path="/missing"), None)
    assert result["statusCode"] == 404
    assert json.loads(result["body"])["title"] == "Not Found"
