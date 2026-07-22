"""Cloudflare Python Workers entry for the hayate example.

Deploy (from this directory, wrangler + Python Workers beta):

    uv run pywrangler dev      # local workerd
    uv run pywrangler deploy   # to Cloudflare
"""

import asyncio

from hayate import Context, Hayate
from hayate.adapters.workers import forward, to_durable_object, to_workers

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


@app.ws("/ws")
async def ws_echo(c: Context, ws):
    """WebSocket echo — the same handler shape as on ASGI (research §5)."""
    await ws.send("hello from hayate on workers")
    async for message in ws:
        if message == "bye":
            break  # server-initiated close (1000)
        await ws.send(message if isinstance(message, bytes) else f"echo: {message}")


@app.get("/counter/:name")
async def counter(c: Context):
    """Forward to the named Durable Object; the response crosses untouched."""
    return await forward(c, c.env.COUNTER.getByName(c.req.param("name")))


@app.get("/do-ws/:name")
async def do_ws(c: Context):
    """WebSocket upgrade THROUGH this app into the Durable Object:
    forward() passes the platform response back untouched, so the
    ``webSocket`` of the 101 survives."""
    return await forward(c, c.env.COUNTER.getByName(c.req.param("name")))


# The factory's name becomes the Durable Object class name and must
# match ``class_name`` in wrangler.toml.
@to_durable_object
def Counter(ctx, env):
    """Runs inside the Durable Object; closures capture ``ctx.storage``."""
    do_app = Hayate()

    @do_app.get("/counter/:name")
    async def count(c: Context):
        n = int((await ctx.storage.get("n")) or 0) + 1
        await ctx.storage.put("n", n)
        return c.json({"name": c.req.param("name"), "count": n})

    @do_app.ws("/do-ws/:name")
    async def ws_in_do(c: Context, ws):
        await ws.send(f"hello from durable object {c.req.param('name')}")
        async for message in ws:
            if message == "bye":
                break
            await ws.send(f"do-echo: {message}")

    return do_app


Default = to_workers(app)
