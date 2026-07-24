"""Public decorator types must remain usable under strict mypy."""

from collections.abc import Callable, Coroutine
from typing import Any

from hayate import Context, Hayate, Next, Response

app = Hayate()


@app.get("/books/:id")
async def show_book(c: Context) -> Response:
    return c.json({"id": c.req.param("id")})


@app.post("/books")
async def create_book(c: Context) -> Response:
    return c.json(await c.req.json(), 201)


@app.use
async def request_id(c: Context, next_: Next) -> None:
    c.set("request_id", "test")
    await next_()


@app.use("/admin/*")
async def admin_only(c: Context, next_: Next) -> None:
    await next_()


book_handler: Callable[[Context], Coroutine[Any, Any, Response]] = show_book
create_handler: Callable[[Context], Coroutine[Any, Any, Response]] = create_book
request_middleware: Callable[[Context, Next], Coroutine[Any, Any, None]] = request_id
admin_middleware: Callable[[Context, Next], Coroutine[Any, Any, None]] = admin_only


@app.on_error
async def handle_error(error: Exception, c: Context) -> Response:
    return c.json({"error": str(error)}, 500)


error_handler: Callable[[Exception, Context], Coroutine[Any, Any, Response]] = handle_error
