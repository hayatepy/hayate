# Changelog

All notable changes to hayate are documented here.

## [0.3.0] - 2026-07-22

First public release. hayate is a web-standards-first Python web
framework inspired by Hono: the Fetch API model (Request / Response /
Headers / URL / URLPattern) is the user-facing surface, and Python-local
protocols (WSGI/ASGI) are demoted to adapter-level details.

### Core

- Fetch-semantics `Request` / `Response` / `Headers` (one-shot bodies,
  `clone()` with stream tee, immutability guard)
- WHATWG `URL` / `URLSearchParams` / `URLPattern` as documented subsets,
  measured against vendored web-platform-tests on every run
  (URLPattern: zero behavioral mismatches within the supported subset;
  URL: 66% of in-scope cases — see docs/conformance.md)
- Routing via URLPattern syntax (`/books/:id(\d+)`, `*`, `:name?`),
  onion middleware, automatic 405 + `Allow`, HEAD→GET fallback
- Errors as RFC 9457 `application/problem+json`, everywhere
- Context helpers: `c.json/text/html/body/redirect`, `c.set_cookie`,
  `c.wait_until` (Workers `ctx.waitUntil` semantics), `c.event_stream`
- `app.request()` — test the app with no server and no test client

### Realtime

- WebSocket routes (`@app.ws`, auto-accept, async iteration)
- Server-Sent Events (`c.event_stream`, WHATWG HTML format)

### Middleware (all zero-dependency)

`logger`, `cors`, `etag`, `compress` (gzip; zstd on 3.14+),
`basic_auth`, `body_limit`, `timeout`, `secure_headers`, `cache`,
`static_files` (single Range / 304 / 416, traversal-safe)

### Validation

- `validator(target, callable)` + `c.req.valid(target)` — msgspec and
  pydantic plug in directly (`msgspec.convert`,
  `TypeAdapter(...).validate_python`); no adapter packages needed

### Runtimes

- ASGI (`uvicorn main:app` works as-is; http + websocket + lifespan)
- Cloudflare Python Workers: `Default = to_workers(app)`
- AWS Lambda (API Gateway HTTP API v2.0 / Function URLs):
  `handler = to_lambda(app)`

### Performance

- Lazy materialization over eager Fetch objects: framework overhead at
  or below Starlette's (static 1.20x, 64 routes 1.93x, stock-middleware
  scenario far ahead) — methodology and caveats in docs/benchmarks.md
- Optional Rust accelerator (`hayate-accel`, source in `accel/`);
  prebuilt wheels land on PyPI in a future release

### Known limits (documented, enforced by tests)

- URL: no IDNA/punycode (non-ASCII hosts raise), no IPv4/IPv6
  canonicalization
- URLPattern: `{}` groups and `+`/`*` modifiers rejected explicitly
- Workers adapter: bodies buffered across FFI; streaming bridge and
  on-platform verification tracked in docs/research/cloudflare.md
