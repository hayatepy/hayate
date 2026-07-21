"""WebSocket routes over the ASGI adapter."""

from _ws import WSClient
from hayate import Context, Hayate, WebSocket


def make_echo_app() -> Hayate:
    app = Hayate()

    @app.ws("/echo/:tag")
    async def echo(c: Context, ws: WebSocket):
        async for message in ws:
            if isinstance(message, str):
                await ws.send(f"{c.req.param('tag')}:{message}")
            else:
                await ws.send(message)

    return app


async def test_text_roundtrip_with_route_param():
    app = make_echo_app()
    async with WSClient(app, "/echo/a") as client:
        await client.send_text("hi")
        assert await client.recv() == {"type": "websocket.send", "text": "a:hi"}


async def test_binary_roundtrip():
    app = make_echo_app()
    async with WSClient(app, "/echo/b") as client:
        await client.send_bytes(b"\x01\x02")
        assert await client.recv() == {"type": "websocket.send", "bytes": b"\x01\x02"}


async def test_unknown_path_rejected_before_accept():
    app = Hayate()
    sent: list[dict] = []
    inbox = [{"type": "websocket.connect"}]

    async def receive():
        return inbox.pop(0)

    async def send(message):
        sent.append(message)

    scope = {
        "type": "websocket",
        "scheme": "ws",
        "path": "/nope",
        "raw_path": b"/nope",
        "query_string": b"",
        "headers": [],
        "server": ("testserver", 80),
    }
    await app(scope, receive, send)
    assert sent == [{"type": "websocket.close", "code": 4404, "reason": "not found"}]


async def test_handler_completion_closes_cleanly():
    app = Hayate()

    @app.ws("/once")
    async def once(c: Context, ws: WebSocket):
        message = await ws.receive()
        await ws.send(f"got:{message}")
        # Returning closes the socket with code 1000.

    async with WSClient(app, "/once") as client:
        await client.send_text("x")
        assert await client.recv() == {"type": "websocket.send", "text": "got:x"}
        closed = await client.recv()
        assert closed["type"] == "websocket.close"
        assert closed["code"] == 1000


async def test_ws_route_not_listed_in_http_allow():
    app = Hayate()

    @app.ws("/only-ws")
    async def handler(c: Context, ws: WebSocket):
        pass

    res = await app.request("/only-ws")
    # No HTTP route exists: plain 404, not 405 with a bogus Allow header.
    assert res.status == 404
