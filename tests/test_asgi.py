"""ASGI adapter: driven directly with in-test scope/receive/send."""

from typing import Any

from hayate import Context, Hayate, Response


async def call_asgi(
    app: Hayate,
    *,
    method: str = "GET",
    path: str = "/",
    query: bytes = b"",
    headers: tuple[tuple[str, str], ...] = (),
    body: bytes = b"",
) -> list[dict[str, Any]]:
    messages: list[dict[str, Any]] = []
    inbox: list[dict[str, Any]] = [{"type": "http.request", "body": body, "more_body": False}]

    async def receive() -> dict[str, Any]:
        if inbox:
            return inbox.pop(0)
        return {"type": "http.disconnect"}

    async def send(message: dict[str, Any]) -> None:
        messages.append(message)

    header_list = [(k.encode(), v.encode()) for k, v in headers]
    if body:
        # Real servers always announce a request body (RFC 9112).
        header_list.append((b"content-length", str(len(body)).encode()))
    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": method,
        "scheme": "http",
        "path": path,
        "raw_path": path.encode(),
        "query_string": query,
        "headers": header_list,
        "server": ("testserver", 80),
        "client": ("127.0.0.1", 1234),
    }
    await app(scope, receive, send)
    return messages


def response_status(messages: list[dict[str, Any]]) -> int:
    return messages[0]["status"]


def response_body(messages: list[dict[str, Any]]) -> bytes:
    return b"".join(m.get("body", b"") for m in messages if m["type"] == "http.response.body")


def response_headers(messages: list[dict[str, Any]]) -> dict[bytes, bytes]:
    return dict(messages[0]["headers"])


async def test_get_roundtrip():
    app = Hayate()

    @app.get("/hello")
    async def hello(c: Context):
        return c.text("hi")

    messages = await call_asgi(app, path="/hello")
    assert response_status(messages) == 200
    assert response_body(messages) == b"hi"
    headers = response_headers(messages)
    assert headers[b"content-type"] == b"text/plain;charset=utf-8"
    assert headers[b"content-length"] == b"2"


async def test_post_body_echo():
    app = Hayate()

    @app.post("/echo")
    async def echo(c: Context):
        return c.body(await c.req.bytes())

    messages = await call_asgi(app, method="POST", path="/echo", body=b"payload")
    assert response_body(messages) == b"payload"


async def test_query_string_reaches_url():
    app = Hayate()

    @app.get("/q")
    async def q(c: Context):
        return c.text(c.req.query("a") or "")

    messages = await call_asgi(app, path="/q", query=b"a=b")
    assert response_body(messages) == b"b"


async def test_host_header_feeds_url():
    app = Hayate()

    @app.get("/")
    async def root(c: Context):
        return c.text(c.req.url.host)

    messages = await call_asgi(app, headers=(("host", "api.example.com"),))
    assert response_body(messages) == b"api.example.com"


async def test_streaming_response_chunks():
    app = Hayate()

    @app.get("/stream")
    async def stream(c: Context):
        async def gen():
            yield b"a"
            yield b"b"

        return c.body(gen())

    messages = await call_asgi(app, path="/stream")
    bodies = [m for m in messages if m["type"] == "http.response.body"]
    assert [m["body"] for m in bodies] == [b"a", b"b", b""]
    assert bodies[0]["more_body"] is True
    assert b"content-length" not in response_headers(messages)


async def test_head_suppresses_body_but_keeps_content_length():
    app = Hayate()

    @app.get("/doc")
    async def doc(c: Context):
        return c.text("hello")

    messages = await call_asgi(app, method="HEAD", path="/doc")
    assert response_headers(messages)[b"content-length"] == b"5"
    assert response_body(messages) == b""


async def test_204_has_no_body_and_no_content_length():
    app = Hayate()

    @app.delete("/x")
    async def delete(c: Context):
        return Response(None, 204)

    messages = await call_asgi(app, method="DELETE", path="/x")
    assert response_status(messages) == 204
    assert b"content-length" not in response_headers(messages)
    assert response_body(messages) == b""


async def test_lifespan_hooks_run():
    app = Hayate()
    events: list[str] = []

    @app.on_start
    async def start():
        events.append("start")

    @app.on_stop
    def stop():  # sync hooks are fine too
        events.append("stop")

    inbox = [{"type": "lifespan.startup"}, {"type": "lifespan.shutdown"}]
    sent: list[dict[str, Any]] = []

    async def receive() -> dict[str, Any]:
        return inbox.pop(0)

    async def send(message: dict[str, Any]) -> None:
        sent.append(message)

    await app({"type": "lifespan"}, receive, send)
    assert events == ["start", "stop"]
    assert [m["type"] for m in sent] == [
        "lifespan.startup.complete",
        "lifespan.shutdown.complete",
    ]


async def test_wait_until_drained_after_response():
    app = Hayate()
    ran: list[bool] = []

    @app.get("/")
    async def root(c: Context):
        async def background():
            ran.append(True)

        c.wait_until(background())
        return c.text("ok")

    await call_asgi(app)
    assert ran == [True]
