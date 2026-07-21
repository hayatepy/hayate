"""Integration: the v0.2 acceptance criterion — the chat sample works."""

import asyncio

from chat import app, rooms

from _ws import WSClient


async def test_index_serves_html():
    res = await app.request("/")
    assert res.status == 200
    assert "text/html" in (res.headers.get("content-type") or "")


async def test_broadcast_between_clients():
    async with WSClient(app, "/ws/lobby") as alice, WSClient(app, "/ws/lobby") as bob:
        await alice.send_text("hello bob")
        assert await bob.recv() == {"type": "websocket.send", "text": "hello bob"}
        assert alice.nothing_received()  # sender does not echo to itself
    assert rooms == {}  # rooms are cleaned up once everyone leaves


async def test_rooms_are_isolated():
    async with WSClient(app, "/ws/a") as one, WSClient(app, "/ws/b") as other:
        await one.send_text("only room a")
        await asyncio.sleep(0.05)
        assert other.nothing_received()
