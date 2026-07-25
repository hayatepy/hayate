"""The common competitive workload as a native Cloudflare Python Worker."""

from hayate import Context, Hayate, Response
from hayate.adapters.workers import to_workers

app = Hayate()


@app.get("/text")
async def text(c: Context) -> Response:
    return c.text("hello")


@app.get("/items/:id")
async def item(c: Context) -> Response:
    item_id = c.req.param("id")
    return c.json({"id": item_id, "name": f"item-{item_id}"})


@app.post("/echo")
async def echo(c: Context) -> Response:
    data = await c.req.json()
    message = data["message"]
    return c.json({"message": message, "length": len(message)})


async def route(c: Context) -> Response:
    return c.text("ok")


for index in range(64):
    app.get(f"/route{index}/:key")(route)


Default = to_workers(app)
