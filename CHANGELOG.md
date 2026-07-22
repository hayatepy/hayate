# Changelog

All notable changes to hayate are documented here.

## [0.6.0] - 2026-07-22

### Changed

- **Router: segment trie for plain-parameter routes.** Patterns made
  only of literal and `:name` segments now match through a segment trie
  — O(path segments) whatever the route count (~0.95 µs flat; the
  many-routes(64) benchmark went 102k → 200k req/s, 3.83x Starlette).
  Regexp constraints, optional params, and wildcards stay on the regex
  tail; **registration order still decides between overlapping dynamic
  routes** (each route carries its registration index), so the tiering
  is invisible to applications — pinned by tests/test_router.py. Known
  trade-off: a single dynamic route pays ~0.4 µs over the previous
  one-regex scan (dynamic-json −8%); DESIGN §14.4 records the numbers
  and the rejected flat-alternation design (9x *worse* at 1024 routes).
- **URL: WHATWG IPv4/IPv6 canonicalization and %2e-aware dot-segment
  removal** — `0x7f.1` → `127.0.0.1` with overflow rejection
  (hosts ending in a number must parse as IPv4), IPv6 parsing with
  RFC 5952 `::`-compressed lowercase serialization, `%2e`/`%2E` dot
  segments, and multi-slash edge cases. **The wpt conformance ratchet
  rose 202 → 246 of 306 in-scope cases (66% → 80.4%)** with zero new
  dependencies and no tables. The remaining gap is the host
  percent-decode → IDNA/UTS-46 pipeline, demand-gated at
  hayatepy/hayate#2 (the rejection error now points there).

## [0.5.0] - 2026-07-22

### Added

- **`hayate.adapters.workers.forward(c, fetcher)`** — forward the
  original platform request to any Fetcher binding (Durable Object
  stub, service binding) and return its response **untouched**.
  Platform extensions survive the crossing, so a websocket upgrade
  passes *through* the outer app into the Durable Object's own
  `@app.ws()` route — verified on a local workerd and in production
  over `wss://`. Caveat (documented): a forwarded response is exactly
  the platform's response; staged response mutations (`c.header()`) do
  not apply to it. `examples/workers/` gains `/do-ws/:name`
  demonstrating the pass-through upgrade, and `/counter/:name` now
  forwards instead of rebuilding the response.

### Changed

- Hot-path micro-optimizations, each measured (DESIGN §14.4 records
  the numbers and the rejected alternatives):
  - Response header wire encoding is memoized (114 → 41 ns per pair) —
    the same pairs were re-encoded on every request.
  - `Headers.get()` takes a single-value fast path (181 → 145 ns).
  - Static route matches share one empty params dict (40 → 31 ns).
  - Header-name interning and per-method dynamic-route indexes were
    measured and rejected — the numbers are recorded so they stay
    settled.

## [0.4.1] - 2026-07-22

### Changed

- **Workers adapter: fewer and thinner FFI crossings** (measured on a
  local workerd; behavior unchanged, DESIGN §14.4 records the survey
  behind these):
  - The request URL is split, not re-parsed — the platform already
    validated it (2.49 µs → 0.25 µs per request).
  - Request headers are taken as-is (`Headers._from_trusted_pairs`): JS
    `Headers` iteration already yields lowercase names.
  - Bodyless requests (null `body` per Fetch) skip the buffered body
    read — previously every GET paid one async FFI round-trip.
  - Response headers cross in one call (`js.Headers.new(pairs)`)
    instead of one `append()` proxy round-trip per header.
- **Workers adapter: Fetch null-body statuses** (101/103/204/205/304)
  drop their body at translation, matching the ASGI adapter —
  `js.Response` throws on a body for these statuses.
- **hayate-accel 0.2.0: multipart boundary scanning in Rust.** The
  splitter uses SIMD substring search (`memchr::memmem`) and copies
  each payload once; `parse_multipart` on a 10.5 MB body drops 5.7 ms →
  0.5 ms (11x). Semantic parsing stays in the single pure-Python path;
  parity between the two splitters is pinned by tests.

### Added

- `SSEMessage` is exported (the type `c.event_stream()` consumes).
- Docstrings on every exported name (public-API audit, DESIGN §18).
- A monthly report-only `wpt refresh` workflow: reruns the conformance
  suites against the *latest* upstream wpt data and opens an issue on
  drift — pinned ratchets prevent regression but cannot detect new spec
  tests.

## [0.4.0] - 2026-07-22

### Added

- **Workers adapter: WebSocket upgrade.** An `Upgrade: websocket` request
  matching an `@app.ws()` route is served through `WebSocketPair`: the
  handler drives the server socket via the exact same `WebSocket` API as
  on ASGI (text/bytes echo, server-initiated close, `async for`), and
  the fetch returns `101` with the client socket
  (`workers.Response(web_socket=...)`). Binary frames are read as
  `ArrayBuffer` (`binaryType` is set on accept — workerd delivers `Blob`
  by default, which only offers async readers). Verified on a local
  workerd. An upgrade request with no matching websocket route falls
  through to normal HTTP handling.
- **Workers adapter: Durable Object mount** — `to_durable_object`:

  ```python
  @to_durable_object
  def Counter(ctx, env):
      app = Hayate()
      ...  # route closures capture ctx.storage (Hono's constructor idiom)
      return app
  ```

  The factory's name becomes the exported class name (workerd registers
  Durable Object classes by `__name__` — it must match `class_name` in
  wrangler.toml). Websocket routes work inside the object too. Verified
  on a local workerd (per-name counters persist in DO storage).
- `examples/workers/`: `/ws` (websocket echo) and `/counter/:name`
  (Durable Object via `getByName` + stub fetch), with the DO binding and
  `new_sqlite_classes` migration in wrangler.toml.

### Changed

- **Workers adapter: deterministic FFI proxy lifecycle.** Every
  `create_proxy` made for a request — the abort listener, the response
  generator, websocket listeners — is now destroyed when that request's
  lifecycle ends (buffered response: at translation; streaming: when the
  stream drains or cancels; websocket: when the connection closes),
  instead of waiting for FinalizationRegistry, which engines do not
  guarantee to run. Measured on workerd: 3,200 requests (400 SSE
  mid-disconnects, 400 websocket cycles) moved RSS 35.4 → 35.9 MB with
  zero errors — allocator noise, no growth trend.
- The abort listener is therefore detached once the response completes;
  an abort firing after completion is no longer mirrored (it had no
  observer by then anyway).

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
