# Middleware

Koa/Hono-style onion composition: code before `await next_()` runs on the
way in, code after runs on the way out.

```python
import time

@app.use
async def server_timing(c, next_):
    start = time.perf_counter()
    await next_()
    dur = (time.perf_counter() - start) * 1000
    c.header("server-timing", f"app;dur={dur:.1f}")
```

Scope middleware with a URLPattern, or attach it to a single route:

```python
app.use("/admin/*", require_admin)

@app.post("/books", validator("json", BookIn.validate))
async def create(c): ...
```

Middleware runs even when no route matches, so CORS headers apply to 404/405
responses too. Returning a `Response` from middleware short-circuits the
chain.

## Built-ins (all zero-dependency)

```python
from hayate.middleware import (
    basic_auth, body_limit, cache, compress, cors, etag,
    logger, rate_limit, request_id, secure_headers, static_files, timeout,
)
```

| Middleware | What it does |
|---|---|
| `logger()` | `METHOD /path -> status (ms)` via `logging` |
| `cors(origin=..., origin_resolver=...)` | Fetch-standard CORS incl. preflight; resolver can inspect `c.env` |
| `etag()` | weak ETags + `If-None-Match` -> 304 (RFC 9110) |
| `compress()` | gzip everywhere, zstd on Python 3.14+ |
| `basic_auth(username=..., password=...)` | RFC 7617, timing-safe |
| `body_limit(max_size=...)` | 413 on declared, buffered, or streamed bodies |
| `timeout(seconds=...)` | 504 via `asyncio.timeout` |
| `secure_headers()` | CSP/HSTS/nosniff/frame/referrer, composed at startup |
| `cache(max_age=...)` | in-process GET micro-cache + `Cache-Control`/`Age` (RFC 9111) |
| `static_files(root=...)` | files with ETag/304, single Range 206/416, traversal-safe |
| `rate_limit(limit=..., window=..., key=...)` | quota + 429/`Retry-After`, advertised via `RateLimit`/`RateLimit-Policy` (draft-ietf-httpapi-ratelimit-headers) |
| `request_id()` | safe `X-Request-ID` generation/preservation, `c.get("request_id")`, and response correlation |

Static assets, Hono-style:

```python
app.use("/assets/*", static_files(root="public", strip_prefix="/assets"))
```

Rate limiting — `key` names the quota partition, and choosing it is a
trust-boundary decision (peer IP behind *your* proxy, an API key, a user id),
so it has no default. Return `None` to skip a request. The bundled store is
in-memory and per-process; inject a `RateLimitStore` over shared storage when
you scale out:

```python
app.use("/api/auth/*", rate_limit(
    limit=10, window=60,
    key=lambda c: c.req.header("cf-connecting-ip"),
))
```

Workers applications can resolve a CORS allowlist from a request-bound
environment without replacing the middleware:

```python
def from_env(c, request_origin):
    allowed = c.env["CORS_ORIGINS"]
    return request_origin if request_origin in allowed else None

app.use(cors(origin_resolver=from_env, credentials=True))
```

Request correlation uses a bounded log-safe value instead of trusting an
arbitrary caller-controlled header. Register it before middleware that reads
the context value:

```python
from hayate.middleware import logger, request_id

app.use(request_id())
app.use(logger())

@app.get("/")
async def home(c):
    application_log.info("home", extra={"request_id": c.get("request_id")})
    return c.text("ok")
```

Set `accept_incoming=False` and provide a generator when a platform-issued
value such as a Cloudflare or Lambda request ID must take precedence.

## Writing your own

A middleware is `async def mw(c, next_)`; a factory returning one is the
idiomatic packaging.
