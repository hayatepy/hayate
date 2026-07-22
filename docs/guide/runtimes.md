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
- Bodies stream across the FFI boundary (JS `ReadableStream` in both
  directions, with a buffered fallback on runtimes that lack the pieces),
  and the JS abort signal is mirrored onto `request.signal`. Verified in
  production: SSE time-to-first-byte 53 ms against 1.55 s total — true
  incremental delivery, not buffering. Details in the
  [research log](https://github.com/hayatepy/hayate/blob/main/docs/research/cloudflare.md).
- `@app.ws()` routes are served through `WebSocketPair`: the same handler
  that runs on ASGI answers `Upgrade: websocket` requests with `101` and
  drives the server socket (text, bytes, clean close — verified in
  production over `wss://`). Every per-request FFI proxy is destroyed
  deterministically when the request ends — no reliance on garbage
  collection.

### Durable Objects

Mount an app per object with `to_durable_object` — build it in the
factory so route closures capture the object's storage (the same idiom
Hono uses in the class constructor). The factory's **name becomes the
exported class name** and must match `class_name` in wrangler.toml:

```python title="entry.py"
from hayate.adapters.workers import to_durable_object

@to_durable_object
def Counter(ctx, env):
    app = Hayate()

    @app.get("/counter/:name")
    async def count(c: Context):
        n = int((await ctx.storage.get("n")) or 0) + 1
        await ctx.storage.put("n", n)
        return c.json({"count": n})

    return app
```

```toml title="wrangler.toml"
[[durable_objects.bindings]]
name = "COUNTER"
class_name = "Counter"

[[migrations]]
tag = "v1"
new_sqlite_classes = ["Counter"]
```

Reach it from a route with `forward()` — it hands the *original*
platform request to any Fetcher binding (a Durable Object stub, a
service binding) and returns the response untouched:

```python
from hayate.adapters.workers import forward

@app.get("/room/:name")
async def room(c: Context):
    return await forward(c, c.env.ROOMS.getByName(c.req.param("name")))
```

Because nothing is rebuilt, platform extensions survive — a websocket
upgrade passes **through** this app into the object's own `@app.ws()`
route (verified in production over `wss://`). One caveat: a forwarded
response is exactly the platform's response, so staged response
mutations (`c.header()`) do not apply to it.

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
