"""Integration test: the v0.1 acceptance criterion.

"A TODO API can be written, with tests, using only web-standard
vocabulary" — routing via URLPattern syntax, errors as RFC 9457 problem
documents, and no server or test client involved.
"""

import itertools
from typing import Any

from hayate import Context, Hayate, HTTPException
from hayate.middleware import cors, logger


def make_app() -> Hayate:
    app = Hayate()
    app.use(logger())
    app.use(cors(origin="*"))

    todos: dict[int, dict[str, Any]] = {}
    ids = itertools.count(1)

    @app.get("/todos")
    async def list_todos(c: Context):
        return c.json(list(todos.values()))

    @app.post("/todos")
    async def create_todo(c: Context):
        data = await c.req.json()
        title = data.get("title")
        if not isinstance(title, str) or not title.strip():
            raise HTTPException(
                400, title="Validation failed", detail="'title' must be a non-empty string"
            )
        todo_id = next(ids)
        todo = {"id": todo_id, "title": title.strip(), "done": False}
        todos[todo_id] = todo
        return c.json(todo, 201, headers={"location": f"/todos/{todo_id}"})

    @app.get(r"/todos/:id(\d+)")
    async def show_todo(c: Context):
        todo = todos.get(int(c.req.param("id") or 0))
        if todo is None:
            raise HTTPException(404, title="Todo not found")
        return c.json(todo)

    @app.put(r"/todos/:id(\d+)")
    async def update_todo(c: Context):
        todo_id = int(c.req.param("id") or 0)
        todo = todos.get(todo_id)
        if todo is None:
            raise HTTPException(404, title="Todo not found")
        data = await c.req.json()
        todo["title"] = data.get("title", todo["title"])
        todo["done"] = bool(data.get("done", todo["done"]))
        return c.json(todo)

    @app.delete(r"/todos/:id(\d+)")
    async def delete_todo(c: Context):
        if todos.pop(int(c.req.param("id") or 0), None) is None:
            raise HTTPException(404, title="Todo not found")
        return c.body(None, 204)

    return app


async def test_full_crud_flow():
    app = make_app()

    created = await app.request("/todos", method="POST", json={"title": "write tests"})
    assert created.status == 201
    todo = await created.json()
    assert created.headers.get("location") == f"/todos/{todo['id']}"
    assert todo["title"] == "write tests"

    listed = await (await app.request("/todos")).json()
    assert listed == [todo]

    updated = await app.request(f"/todos/{todo['id']}", method="PUT", json={"done": True})
    assert (await updated.json())["done"] is True

    deleted = await app.request(f"/todos/{todo['id']}", method="DELETE")
    assert deleted.status == 204

    missing = await app.request(f"/todos/{todo['id']}")
    assert missing.status == 404
    assert missing.headers.get("content-type") == "application/problem+json"


async def test_validation_error_is_problem_json():
    app = make_app()
    res = await app.request("/todos", method="POST", json={"title": "  "})
    assert res.status == 400
    body = await res.json()
    assert body["title"] == "Validation failed"
    assert body["status"] == 400


async def test_non_numeric_id_does_not_match_route():
    app = make_app()
    res = await app.request("/todos/abc")
    assert res.status == 404


async def test_cors_headers_present():
    app = make_app()
    res = await app.request("/todos", headers={"origin": "https://app.example"})
    assert res.headers.get("access-control-allow-origin") == "*"


async def test_method_not_allowed_on_collection():
    app = make_app()
    res = await app.request("/todos", method="PATCH")
    assert res.status == 405
    allow = res.headers.get("allow")
    assert allow is not None and "GET" in allow and "POST" in allow
