# Testing

Because the core performs no I/O, tests call it directly. There is no test
client, no ASGI transport, no socket — and tests run in microseconds.

```python
from main import app


async def test_crud_flow():
    created = await app.request("/todos", method="POST", json={"title": "ship"})
    assert created.status == 201
    todo = await created.json()
    assert created.headers.get("location") == f"/todos/{todo['id']}"

    listed = await (await app.request("/todos")).json()
    assert listed == [todo]

    deleted = await app.request(f"/todos/{todo['id']}", method="DELETE")
    assert deleted.status == 204
```

`app.request()` accepts `method`, `headers`, `body` (str / bytes / async
iterable), and `json` (sets `content-type` and serializes for you). It
returns a real `Response` — read it with `await res.json()` / `.text()` /
`.bytes()`.

Setup: `pytest` + `pytest-asyncio` with `asyncio_mode = "auto"`:

```toml title="pyproject.toml"
[tool.pytest.ini_options]
asyncio_mode = "auto"
```

## What this buys you

- Middleware, routing, error handling, and `c.wait_until` background work all
  execute exactly as in production (background tasks are drained before
  `app.request()` returns, so assertions are deterministic).
- Handlers that stream (`SSE`, chunked bodies) can be collected with
  `await res.bytes()`.
- WebSocket handlers are tested through the ASGI adapter with an in-process
  driver — see
  [`tests/_ws.py`](https://github.com/hayatepy/hayate/blob/main/tests/_ws.py)
  for the ~60-line client the framework's own suite uses.

## Testing against real transports

Nothing stops you from booting uvicorn in a fixture for end-to-end coverage —
but the framework's own 250+ tests, including the chat sample's broadcast
tests, run entirely in-process.
