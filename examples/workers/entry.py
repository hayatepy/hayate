"""Cloudflare Python Workers entry for the hayate example.

Deploy (from this directory, wrangler + Python Workers beta):

    uv run pywrangler dev      # local workerd
    uv run pywrangler deploy   # to Cloudflare
"""

import asyncio

from hayate import Context, Hayate
from hayate.adapters.workers import to_workers

app = Hayate()


@app.get("/")
async def hello(c: Context):
    return c.json(
        {
            "framework": "hayate",
            "runtime": "cloudflare-python-workers",
            "url": c.req.url.href,
        }
    )


@app.get("/hello/:name")
async def greet(c: Context):
    return c.json({"hello": c.req.param("name")})


# Verification routes for the FFI streaming bridge (research §5): on a
# streaming-capable runtime these must arrive incrementally, not buffered.


@app.get("/stream")
async def stream(c: Context):
    async def chunks():
        for i in range(3):
            yield f"chunk {i}\n".encode()

    return c.body(chunks(), headers={"content-type": "text/plain"})


@app.get("/events")
async def events(c: Context):
    async def source():
        for i in range(3):
            yield {"data": f"tick {i}"}
            await asyncio.sleep(0.5)

    return c.event_stream(source())


@app.post("/echo")
async def echo(c: Context):
    return c.json({"got": await c.req.json()})


Default = to_workers(app)
