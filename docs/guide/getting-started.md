# Getting started

## Install

```sh
uv init myapp && cd myapp
uv add hayate uvicorn
```

## A complete TODO API

```python title="main.py"
import itertools

from hayate import Context, Hayate, HTTPException

app = Hayate()

todos: dict[int, dict] = {}
ids = itertools.count(1)


@app.get("/todos")
async def list_todos(c: Context):
    return c.json(list(todos.values()))


@app.post("/todos")
async def create_todo(c: Context):
    data = await c.req.json()
    title = data.get("title")
    if not isinstance(title, str) or not title.strip():
        raise HTTPException(400, title="Validation failed",
                            detail="'title' must be a non-empty string")
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


@app.delete(r"/todos/:id(\d+)")
async def delete_todo(c: Context):
    if todos.pop(int(c.req.param("id") or 0), None) is None:
        raise HTTPException(404, title="Todo not found")
    return c.body(None, 204)
```

```sh
uv run uvicorn main:app --reload
```

What you get for free:

- `POST /todos` with a bad body answers **RFC 9457**
  `application/problem+json` — no invented error format.
- `PATCH /todos` answers **405 with an `Allow` header** (RFC 9110).
- `HEAD /todos` reuses the GET handler with the body stripped at the
  transport.
- `/todos/abc` doesn't match the `(\d+)` pattern and falls through to 404.

## Test it without a server

```python title="test_main.py"
from main import app


async def test_create_and_fetch():
    created = await app.request("/todos", method="POST", json={"title": "ship"})
    assert created.status == 201
    todo = await created.json()

    fetched = await app.request(f"/todos/{todo['id']}")
    assert (await fetched.json())["title"] == "ship"
```

Run with `pytest` (plus `pytest-asyncio` in auto mode). No fixtures, no
transport, no mocking — `app.request()` calls the same pure
`fetch(Request) -> Response` core the adapters call.
