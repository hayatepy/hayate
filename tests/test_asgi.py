"""ASGI adapter: driven directly with in-test scope/receive/send."""

import tempfile
from typing import Any

from hayate import Context, File, FormDataError, FormDataLimits, Hayate, Response
from hayate.middleware import current_request_id, request_id


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


async def test_request_id_crosses_asgi_adapter():
    app = Hayate()
    app.use(request_id())
    seen: list[str | None] = []

    @app.get("/")
    async def root(c: Context):
        seen.append(current_request_id())
        return c.text(c.get("request_id"))

    messages = await call_asgi(
        app,
        headers=(("x-request-id", "asgi-request-123"),),
    )
    assert response_body(messages) == b"asgi-request-123"
    assert response_headers(messages)[b"x-request-id"] == b"asgi-request-123"
    assert seen == ["asgi-request-123"]
    assert current_request_id() is None


async def test_post_body_echo():
    app = Hayate()

    @app.post("/echo")
    async def echo(c: Context):
        return c.body(await c.req.bytes())

    messages = await call_asgi(app, method="POST", path="/echo", body=b"payload")
    assert response_body(messages) == b"payload"


async def test_post_stream_preserves_asgi_chunks():
    app = Hayate()

    @app.post("/stream")
    async def stream(c: Context):
        assert c.req.raw.body is not None
        chunks = [chunk async for chunk in c.req.raw.body]
        return c.json({"chunks": [chunk.decode() for chunk in chunks]})

    messages: list[dict[str, Any]] = []
    inbox = [
        {"type": "http.request", "body": b"one", "more_body": True},
        {"type": "http.request", "body": b"", "more_body": True},
        {"type": "http.request", "body": b"two", "more_body": False},
    ]

    async def receive() -> dict[str, Any]:
        return inbox.pop(0)

    async def send(message: dict[str, Any]) -> None:
        messages.append(message)

    await app(
        {
            "type": "http",
            "method": "POST",
            "scheme": "http",
            "path": "/stream",
            "raw_path": b"/stream",
            "query_string": b"",
            "headers": [(b"host", b"testserver"), (b"transfer-encoding", b"chunked")],
        },
        receive,
        send,
    )

    assert response_body(messages) == b'{"chunks":["one","two"]}'


async def test_chunked_asgi_multipart_spools_without_buffering_the_upload():
    app = Hayate()
    limits = FormDataLimits(
        max_body_bytes=512,
        max_file_bytes=128,
        max_field_bytes=32,
        max_parts=2,
        max_header_bytes=128,
        file_memory_bytes=4,
    )

    @app.post("/upload")
    async def upload(c: Context):
        form = await c.req.form_data(limits)
        file = form.get("file")
        assert isinstance(file, File)
        result = {
            "spooled": file.spooled,
            "size": file.size,
            "body": (await file.text()),
        }
        await form.close()
        return c.json(result)

    boundary = "asgi-boundary"
    body = (
        b"--"
        + boundary.encode()
        + b'\r\nContent-Disposition: form-data; name="file"; filename="a.txt"\r\n'
        + b"Content-Type: text/plain\r\n\r\n"
        + b"streamed-content"
        + b"\r\n--"
        + boundary.encode()
        + b"--\r\n"
    )
    chunks = [body[offset : offset + 3] for offset in range(0, len(body), 3)]
    inbox = [
        {
            "type": "http.request",
            "body": chunk,
            "more_body": index < len(chunks) - 1,
        }
        for index, chunk in enumerate(chunks)
    ]
    messages: list[dict[str, Any]] = []

    async def receive() -> dict[str, Any]:
        return inbox.pop(0)

    async def send(message: dict[str, Any]) -> None:
        messages.append(message)

    await app(
        {
            "type": "http",
            "method": "POST",
            "scheme": "http",
            "path": "/upload",
            "raw_path": b"/upload",
            "query_string": b"",
            "headers": [
                (b"host", b"testserver"),
                (b"transfer-encoding", b"chunked"),
                (
                    b"content-type",
                    f"multipart/form-data; boundary={boundary}".encode(),
                ),
            ],
        },
        receive,
        send,
    )

    assert response_status(messages) == 200
    assert response_body(messages) == (b'{"spooled":true,"size":16,"body":"streamed-content"}')


async def test_multipart_disconnect_aborts_and_closes_partial_spool(monkeypatch):
    opened = []
    real_temporary_file = tempfile.TemporaryFile

    def tracked_temporary_file(*args, **kwargs):
        file = real_temporary_file(*args, **kwargs)
        opened.append(file)
        return file

    monkeypatch.setattr(tempfile, "TemporaryFile", tracked_temporary_file)
    app = Hayate()
    limits = FormDataLimits(
        max_body_bytes=512,
        max_file_bytes=128,
        max_field_bytes=32,
        max_parts=2,
        max_header_bytes=128,
        file_memory_bytes=2,
    )

    @app.post("/upload")
    async def upload(c: Context):
        try:
            await c.req.form_data(limits)
        except FormDataError:
            return c.json({"aborted": c.req.signal.aborted}, 400)
        raise AssertionError("a disconnected multipart body must not parse")

    boundary = "disconnect-boundary"
    partial = (
        b"--"
        + boundary.encode()
        + b'\r\nContent-Disposition: form-data; name="file"; filename="a.bin"\r\n\r\n'
        + b"x" * 64
    )
    inbox = [
        {"type": "http.request", "body": partial, "more_body": True},
        {"type": "http.disconnect"},
    ]
    messages: list[dict[str, Any]] = []

    async def receive() -> dict[str, Any]:
        return inbox.pop(0)

    async def send(message: dict[str, Any]) -> None:
        messages.append(message)

    await app(
        {
            "type": "http",
            "method": "POST",
            "scheme": "http",
            "path": "/upload",
            "raw_path": b"/upload",
            "query_string": b"",
            "headers": [
                (b"host", b"testserver"),
                (b"transfer-encoding", b"chunked"),
                (
                    b"content-type",
                    f"multipart/form-data; boundary={boundary}".encode(),
                ),
            ],
        },
        receive,
        send,
    )

    assert response_status(messages) == 400
    assert response_body(messages) == b'{"aborted":true}'
    assert opened
    assert all(file.closed for file in opened)


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


async def test_url_is_lazy_until_application_code_reads_it():
    app = Hayate()

    @app.get("/lazy")
    async def lazy(c: Context):
        assert c.req.raw._url_loader is not None
        url = c.req.url
        assert c.req.raw._url_loader is None
        assert c.req.raw._url_source is None
        return c.json(
            {
                "href": url.href,
                "pathname": url.pathname,
                "query": c.req.query("x"),
            }
        )

    messages = await call_asgi(
        app,
        path="/before/%2e%2e/lazy",
        query=b"x=a%2Fb",
        headers=(("host", "API.EXAMPLE.COM:80"),),
    )
    assert response_body(messages) == (
        b'{"href":"http://api.example.com/lazy?x=a%2Fb","pathname":"/lazy","query":"a/b"}'
    )


async def test_sending_response_does_not_materialize_its_headers():
    app = Hayate()
    produced: list[Response] = []

    @app.get("/")
    async def root(c: Context):
        response = c.text("hello")
        produced.append(response)
        return response

    messages = await call_asgi(app)

    assert response_headers(messages) == {
        b"content-type": b"text/plain;charset=utf-8",
        b"content-length": b"5",
    }
    assert produced[0]._headers is None


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
