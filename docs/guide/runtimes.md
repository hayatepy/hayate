# Runtimes

The app core is a pure function — `await app.fetch(request)` — that performs
no I/O. Adapters translate transport events into that call, which is why the
same `app` runs unchanged everywhere.

## ASGI (uvicorn, hypercorn, granian)

The `Hayate` instance **is** an ASGI callable:

```sh
uvicorn main:app
```

HTTP, WebSocket, and lifespan (`@app.on_start` / `@app.on_stop`) are handled.
You never see `scope` / `receive` / `send`.

## Cloudflare Python Workers

```python title="entry.py"
from hayate.adapters.workers import to_workers
from main import app

Default = to_workers(app)
```

- Single-step translation (JS `Request` → hayate `Request`) — no ASGI detour,
  unlike the FastAPI integration.
- `c.env` receives the Workers bindings (`c.env.KV`, `c.env.DB`, ... —
  awaitable JS proxies pass straight through).
- `c.wait_until` forwards to the platform `ctx.waitUntil`.
- Current limits: bodies are buffered across the FFI boundary; the abort
  signal is not yet bridged.

A ready-to-deploy project lives at
[`examples/workers/`](https://github.com/hayatepy/hayate/tree/main/examples/workers).

## AWS Lambda (Function URLs / API Gateway HTTP API v2.0)

```python title="lambda_function.py"
from hayate.adapters.aws import to_lambda
from main import app

handler = to_lambda(app)
```

Binary bodies are base64-encoded per the payload contract; `Set-Cookie`
headers map to the `cookies` list so they are never comma-joined;
`c.wait_until` work is drained before the invocation returns.

## Testing

`await app.request(...)` is the fourth "runtime" — it drives the same core
with no adapter at all. See [Testing](testing.md).
