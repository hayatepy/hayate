"""Packaged AWS Lambda Runtime Interface Emulator acceptance application."""

from __future__ import annotations

from hayate import Context, Hayate
from hayate.adapters.aws import to_lambda

app = Hayate()


@app.post("/inspect/:item_id")
async def inspect_request(c: Context):
    return c.json(
        {
            "method": c.req.method,
            "item_id": c.req.param("item_id"),
            "query": c.req.query("q"),
            "session": c.req.cookies.get("session"),
            "scheme": c.req.url.protocol,
            "body": await c.req.json(),
        },
        201,
    )


@app.get("/cookies")
async def response_cookies(c: Context):
    c.set_cookie("sid", "abc", http_only=True, secure=True, same_site="Lax")
    c.set_cookie("theme", "dark")
    return c.text("cookies")


@app.get("/binary")
async def binary(c: Context):
    return c.body(b"\x00\xff", headers={"content-type": "application/octet-stream"})


handler = to_lambda(app)
