"""The common competitive workload implemented with FastAPI."""

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, PlainTextResponse

app = FastAPI(openapi_url=None, docs_url=None, redoc_url=None)


@app.get("/text", response_class=PlainTextResponse)
async def text():
    return PlainTextResponse("hello")


@app.get("/items/{item_id}", response_class=JSONResponse)
async def item(item_id: str):
    return JSONResponse({"id": item_id, "name": f"item-{item_id}"})


@app.post("/echo", response_class=JSONResponse)
async def echo(request: Request):
    data = await request.json()
    message = data["message"]
    return JSONResponse({"message": message, "length": len(message)})


async def route(key: str):
    return PlainTextResponse("ok")


for index in range(64):
    app.add_api_route(
        f"/route{index}/{{key}}",
        route,
        methods=["GET"],
        response_class=PlainTextResponse,
    )
