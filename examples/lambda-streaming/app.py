"""Native Python Lambda response-streaming acceptance application."""

from __future__ import annotations

import asyncio

from hayate import Context, Hayate

app = Hayate()


@app.get("/stream")
async def stream(c: Context):
    async def chunks():
        yield b"first\n"
        await asyncio.sleep(0.5)
        yield b"second\n"

    c.set_cookie("sid", "streamed", http_only=True, secure=True)
    return c.body(
        chunks(),
        202,
        headers=[
            ("content-type", "text/plain;charset=utf-8"),
            ("x-stream", "hayate"),
            ("x-value", "one"),
            ("x-value", "two"),
        ],
    )
