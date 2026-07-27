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

### Keep Django or FastAPI during an incremental migration

`ASGIPathDispatcher` keeps independent ASGI applications under explicit path
prefixes while Hayate owns the remaining routes:

```python title="application.py"
import os

from django.core.asgi import get_asgi_application
from hayate.adapters import ASGIPathDispatcher

from main import app

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "legacy.settings")
django_application = get_asgi_application()

application = ASGIPathDispatcher(
    app,
    {"/legacy": django_application},
)
```

Run `uvicorn application:application`. A Django URL such as `admin/` is now
available at `/legacy/admin/`; Hayate routes remain at their original paths.
The dispatcher uses longest path-segment matching and extends ASGI
`root_path`, so nested applications see the prefix without adding it to their
own route declarations. The same composition works for a FastAPI application:

```python
from hayate.adapters import ASGIPathDispatcher
from legacy_api import app as legacy_api
from main import app

application = ASGIPathDispatcher(
    app,
    {"/legacy-api": legacy_api},
)
```

This boundary lets an ASGI deployment retain Django admin, models, migrations,
or existing FastAPI endpoints while new HTTP/MCP paths move independently.
Django's asynchronous ORM methods can be called from Hayate handlers; wrap
transactional synchronous ORM sections with `sync_to_async()` as described in
the [Django async documentation](https://docs.djangoproject.com/en/6.0/topics/async/).

Mounted applications are independent:

- their middleware, authentication, CORS, and OpenAPI documents are not merged
  into Hayate;
- the root application owns the ASGI lifespan scope. Initialize and stop any
  mounted application's lifecycle resources in the composition root;
- mounted prefixes are an ASGI deployment feature. Cloudflare Workers keeps
  the direct Fetch adapter below and does not bundle or execute Django/FastAPI.

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
- Short synchronous handlers run inline on Pyodide, which has no threads;
  handlers that perform I/O remain `async def`.
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

### HTTP throughput compatibility mode

Cloudflare changed Python Workers from module-level handlers to
`WorkerEntrypoint` on 2025-08-14. The class entrypoint above is the default
and supports named RPC methods. For an HTTP-only Worker where warm throughput
has priority, Hayate can use Cloudflare's explicitly supported compatibility
flag to skip the class RPC conversion wrapper:

```python title="entry.py"
from hayate.adapters.workers import to_workers_global
from main import app

on_fetch = to_workers_global(app)
```

```toml title="wrangler.toml"
compatibility_date = "2026-07-01"
compatibility_flags = [
  "python_workers",
  "disable_python_no_global_handlers",
]
```

This mode still supports bindings, `c.wait_until`, streaming bodies, SSE, and
WebSockets. It does not provide named `WorkerEntrypoint` RPC methods or other
class handlers such as `scheduled`; use `to_workers(app)` when those are
needed. The native benchmark publishes both modes and labels the global
handler as a compatibility path rather than presenting it as Cloudflare's
current default.

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
Its Wrangler `main` is `src/entry.py`, so only application source under
`src/` is discovered as a local Python module; project virtual environments,
tests, and deployment-management scripts stay outside the module root.

### Smaller Python uploads

Wrangler can omit modules that cannot execute in a Workers deployment. The
example uses:

```toml title="wrangler.toml"
[python_modules]
exclude = [
  "**/*.pyc",
  "**/__pycache__/**",
  "**/*.dist-info/**",
  "asgi.py",
  "hayate/adapters/asgi.py",
  "hayate/adapters/aws.py",
  "workers/wsgi.py",
]
```

This keeps the Fetch/Workers adapter, WebSocket support, Durable Objects, and
the full URL implementation. The `*.dist-info` rule means
`importlib.metadata` cannot inspect installed distributions at runtime; omit
that one rule if your application needs package metadata. Do not exclude the
`uts46` package: Hayate imports its mapping table only when constructing a URL
with a non-ASCII host, but it is required to preserve the framework's complete
WHATWG URL behavior.

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
