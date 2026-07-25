"""The common competitive workload implemented with hayate."""

from hayate import Context, Hayate

app = Hayate()


@app.get("/text")
async def text(c: Context):
    return c.text("hello")


@app.get("/items/:id")
async def item(c: Context):
    item_id = c.req.param("id")
    return c.json({"id": item_id, "name": f"item-{item_id}"})


@app.post("/echo")
async def echo(c: Context):
    data = await c.req.json()
    message = data["message"]
    return c.json({"message": message, "length": len(message)})


async def route(c: Context):
    return c.text("ok")


for index in range(64):
    app.get(f"/route{index}/:key")(route)
