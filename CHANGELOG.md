# Changelog

All notable changes to hayate are documented here.

## [0.3.2] - 2026-07-22

### Added

- **Workers adapter: FFI streaming bridge.** An async-iterable response
  body now crosses as a JS `ReadableStream` (`ReadableStream.from()`,
  chunks pre-converted to `Uint8Array`), so SSE and chunked responses
  stream instead of buffering; a `ReadableStream` request body is
  surfaced to the app as `AsyncIterable[bytes]`. Runtimes without the
  pieces keep the buffered crossing. On-workerd verification is tracked
  in docs/research/cloudflare.md §5 (it requires a PyPI release, because
  pywrangler vendors dependencies from PyPI).
- **Workers adapter: AbortSignal bridge.** The JS `request.signal` —
  reached via the workers-py wrapper's `js_object`, which is the only
  place the wrapper exposes it — is mirrored onto `request.signal`, so
  handlers can observe client disconnects.
- `examples/workers/`: `/stream`, `/events` (SSE), and `/echo` routes
  for on-workerd verification of the bridges.

### Changed

- Build backend: hatchling → `uv_build`. Wheel contents verified
  identical (modules, `py.typed`, bundled LICENSE now via explicit PEP
  639 `license-files`); the sdist is the lean src-layout shape.
- Accelerator: pyo3 0.26 → 0.29 (`downcast` → `cast`), Rust edition
  2024. Behavioral identity re-verified against the stdlib path.

### Fixed

- wpt data files are read as UTF-8 explicitly; test collection no longer
  crashes on Windows locales such as cp932.

### CI

- GitHub Actions bumped to Node 24-native majors (checkout v7,
  upload-artifact v7, download-artifact v8, setup-uv v9, Pages v5).
- Workflows hardened to a clean zizmor audit: every action pinned to a
  commit SHA, least-privilege `permissions`, `persist-credentials:
  false`, job timeouts, superseded PR runs cancelled, and no cache
  restore in the release build. A zizmor job now audits the workflows
  on every run.
- Dependabot keeps the action SHA pins, the uv lockfile, and the
  accelerator's cargo dependencies fresh (weekly, grouped).
- Evaluated the `ty` type checker: not adopted at 0.0.62 (false
  positives on the Fetch-standard `bytes()` name and on guarded
  platform imports) — revisit at 1.0.

## [0.3.1] - 2026-07-22

### Fixed

- **Workers adapter**: on workerd the fetch handler receives workers-py's
  Python `Request` wrapper (readers: `bytes()` / `headers.items()`), not a
  raw JS proxy (`arrayBuffer()` / `headers.entries()`). The adapter now
  supports both shapes. Found by running `examples/workers/` on a local
  workerd; a regression test pins the wrapper shape.

### Added

- Documentation site (MkDocs Material + mkdocstrings) with an in-browser
  Pyodide playground and `llms.txt`: <https://hayatepy.github.io/hayate/>
- `examples/workers/` — a ready-to-run Cloudflare Python Workers project.

## [0.3.0] - 2026-07-22

First public release. hayate is a web-standards-first Python web
framework inspired by Hono: the Fetch API model (Request / Response /
Headers / URL / URLPattern) is the user-facing surface, and Python-local
protocols (WSGI/ASGI) are demoted to adapter-level details.
Maintained by Yusuke Hayashi under the `hayatepy` organization.

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
