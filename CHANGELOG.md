# Changelog

All notable changes to hayate are documented here.

## [Unreleased]

### Added

- Add a digest-pinned AWS Lambda Python 3.14 packaged-runtime gate that builds
  the current wheel and verifies the native payload-v2 adapter through the
  Lambda Runtime Interface Emulator without ASGI or Mangum.

### Fixed

- Reject unsupported Lambda event payload versions with actionable errors,
  honor case-insensitive forwarded host/scheme headers, and safely base64
  encode invalid UTF-8 bodies even when their declared media type is textual.

## [0.13.0] - 2026-07-27

### Added

- Add resource-bounded streaming multipart parsing with configurable body,
  file, field, part-count, and header limits. Native Python uploads spill
  beyond a configurable memory threshold to temporary files, while
  Workers/Pyodide remains disk-free and fails closed at the same explicit
  limits. Uploaded `File` values retain `bytes()`/`text()` compatibility and
  add async chunk streaming plus deterministic cleanup. Form validator
  middleware closes successfully parsed uploads after downstream handling.
- Add a zero-dependency `ASGIPathDispatcher` for longest-prefix composition
  with existing Django, FastAPI, or other ASGI applications. Mounted HTTP and
  WebSocket scopes receive corrected `path`, `raw_path`, and `root_path`
  values; the root remains the explicit lifespan owner, and the direct
  Cloudflare Fetch path remains unchanged.
- Add locked real-framework gates that serve Django 6.0 admin, FastAPI 0.140
  endpoints/OpenAPI, and Hayate routes through one composed ASGI callable.
- Add a dated, machine-validated competitive capability matrix for Hayate,
  FastAPI, Django, and Hono. Every Hayate first-party claim requires checked
  local evidence, every competitor claim requires a documentation source, and
  generated conclusions retain Django's full-stack and Hono's JavaScript-edge
  advantages instead of declaring a universal winner.
- Record a new publication-profile competitive benchmark for Hayate 0.12.1,
  including the exact source commit, raw samples, resolved dependency versions,
  common HTTP contract, and raw-ASGI transport ceiling. The optimized ASGI path
  reaches 90.3% of that ceiling across the shared workload.

### Changed

- Defer complete ASGI request URL construction, including scheme, authority,
  and query decoding, until application code observes `c.req.url`; preserve
  the trusted canonical pathname for routing; and send response header pairs
  without materializing a mutable `Headers` object.
  Body reads use a concrete one-shot ASGI iterator instead of registering an
  async-generator finalizer for every request. The no-global-middleware route
  hit path also avoids a redundant resolver tuple while retaining the same
  Fetch API and HTTP behavior.
- Force competitive benchmark setup to rebuild the current Hayate checkout
  even when its package version is unchanged, preventing a stale candidate
  wheel from being reported under a newer Git commit.

## [0.12.1] - 2026-07-27

### Fixed

- Preserve route-level middleware in the optimized adapter path when an
  application has no global middleware. Native Workers now execute validators
  and every other route middleware through the same contract as `fetch()` and
  ASGI.

## [0.12.0] - 2026-07-27

### Added

- Extend the dependency-free request validator from JSON, form, and query
  input to decoded route parameters, Fetch-normalized headers, and parsed
  cookies.

## [0.11.2] - 2026-07-26

### Changed

- Link the canonical ecosystem start page, production golden app, and tested
  compatibility evidence from the package description and core documentation.

## [0.11.1] - 2026-07-26

### Fixed

- Load the public `hayate.adapters.ASGIAdapter` export lazily so Workers-only
  deployments can omit ASGI and AWS adapter modules without breaking package
  import. The real-workerd gate now builds Wrangler's dry-run bundle, verifies
  every documented exclusion against its contents, records compressed upload
  size, and retains the UTS-46 internationalized-host contract.
- Put the Workers example entrypoint under `src/`, making that directory
  Wrangler's module root so project virtual environments, tests, and
  management scripts cannot be discovered as application modules.

## [0.11.0] - 2026-07-26

### Added

- Add a cross-repository compatibility gate that builds the candidate Hayate
  wheel and tests the public auth, fetch, MCP, OpenAPI, and scaffold heads in
  disposable locked environments. Pull requests run a bounded smoke profile;
  a weekly and manually dispatchable full profile adds both generated
  Workers variants. Reports record exact commits, runtimes, commands, wheel
  provenance, and failure output.
- Add a locked, same-workload competitive benchmark against FastAPI, Django,
  and Hono. It records app import, server readiness, cold start, production
  dependency closure, compressed deployment payload, per-scenario HTTP
  throughput, and a 14-point common HTTP contract as raw machine-readable
  samples.
- Add PR smoke verification plus monthly and manually dispatchable full
  benchmark automation. Reports include the Git commit, machine and tool
  metadata, resolved transitive versions, and every raw sample.
- Let the release workflow run manually as a non-publishing dry run through
  the same test, dependency-audit, build, SPDX SBOM, and attestation path used
  by immutable release tags. Tag pushes remain the only publishing trigger.
- Use checksum-pinned official oha release binaries as the load generator,
  avoiding a vulnerable transitive dependency in autocannon's current
  `hyperid`/`uuid` chain.
- Add a native Cloudflare Workers profile that compares Hayate and Hono on
  the same locked Wrangler/workerd runtime without ASGI. An SDK-only Python
  control attributes the runtime boundary. It records upload size, local
  startup, throughput, latency, CPU, RSS, and the shared HTTP contract.
- Add `to_workers_global(app)` for HTTP-focused Python Workers that explicitly
  opt into Cloudflare's global-handler compatibility flag. The benchmark
  reports this separately from the current `WorkerEntrypoint` default and
  includes direct-JS controls for both entrypoint boundaries.
- Let the native Workers benchmark select named target subsets for focused,
  reproducible diagnostics without modifying the runner.

### Changed

- Fuse native Workers request handling and response conversion into one
  direct path. On threadless Pyodide, short synchronous handlers run inline;
  synchronous entrypoints return a platform `Response` without manufacturing
  a Python coroutine.
- Defer Workers URL, request/response headers, abort-signal bridges, execution
  contexts, UTF-8 response encoding, and body reads until application code
  observes them. Regular HTTP responses use the platform `Response`
  constructor directly while WebSocket upgrades retain the SDK extension.
- Construct trusted Workers requests, contexts, and text responses directly in
  their final lazy state; cache the most recent platform `ResponseInit`; and
  bypass wrapper-shape probes on the known global-handler request path.
- Add a semantics-preserving terminal-parameter routing tier for unambiguous
  `/literal/:name` routes while retaining registration order for overlaps.
- Import the UTS-46 mapping table only when a non-ASCII host is constructed.
  ASCII and platform-validated request URLs avoid the table at startup while
  the complete 306/306 in-scope WHATWG URL result remains unchanged.
- Exclude bytecode caches, distribution metadata, and non-Workers adapters
  from example and benchmark Worker uploads. The metadata trade-off is
  documented, and every Python benchmark target uses the same exclusion list.
- Reach the framework-free Python runtime ceiling on the reproducible native
  Workers workload through the explicit global-handler compatibility path:
  2,684.6 versus raw Python's 2,686.1 requests/second geometric mean (99.94%).
  The class entrypoint reaches 98.74% of its direct-JS control. Hono remains
  3.21% ahead while Hayate passes 14/14 versus 12/14 HTTP contract cases.
  All 72 samples and 1,626,628 requests are free of errors, timeouts, and
  non-2xx responses; startup, upload size, CPU, and memory gaps remain
  reported rather than hidden.

### Fixed

- Harden the Cloudflare FFI lifecycle under load: GET/HEAD no longer cross a
  forbidden null body, abort listeners attach only when observed, request
  stream readers and transient proxies are released deterministically, and
  response headers are owned by the Workers SDK. Benchmark samples containing
  transport errors or non-2xx responses are rejected rather than reported as
  inflated throughput.

## [0.10.0] - 2026-07-24

### Added

- Complete the WHATWG special-host pipeline with strict percent decoding and
  non-transitional UTS-46 domain-to-ASCII processing. Internationalized,
  mapped, and percent-encoded hosts now canonicalize exactly like the pinned
  web-platform-tests vectors.

### Changed

- Raise the in-scope URL conformance ratchet from 246/306 (80.4%) to
  306/306 (100%), including the final path percent-encode edge case.
- Add the focused, pure-Python `uts46` package as the core's only runtime
  dependency; it has no transitive runtime dependencies and is portable to
  Pyodide/Cloudflare Workers.
- Correct README benchmark summaries to the measured 1.27x simple-route and
  3.83x 64-route results.
- Add model-based invariant tests for URL, search parameters, headers,
  cookies, and routing.
- Audit locked dependencies on every change and publish an SPDX SBOM plus
  GitHub build and SBOM attestations with each release.

## [0.9.0] - 2026-07-24

### Added

- Add context-aware CORS origin resolution through
  `cors(origin_resolver=...)`, including async resolvers, so runtime bindings
  can supply per-request allowlists without replacing the middleware.
- Add strict public typing fixtures and type-preserving generic signatures
  for route decorators, hooks, and middleware registration.

### Changed

- Mark the distribution as typed and run strict mypy validation in CI.
- Tighten internal typing across the ASGI, Workers, response, WebSocket,
  static-file, compression, cache, form-data, and JSON paths without changing
  their runtime contracts.

## [0.8.1] - 2026-07-24

### Changed

- Correct the public status and ecosystem documentation for the current 0.8
  line.
- Harden releases: publishing now requires an immutable `v*` tag whose name
  matches `project.version`, and a successful PyPI publish creates the
  corresponding GitHub Release.
- Add the documentation URL to package metadata.

## [0.8.0] - 2026-07-23

### Added

- **`app.routes` and the `Route` type are public.** A read-only,
  registration-ordered tuple of every route (`method`, `pattern`,
  `handler`, `middleware`) — the introspection surface tooling needs,
  and the same shape Hono exposes. Driven by hayate-openapi, whose
  generator walks it as its single source of route truth.

## [0.7.0] - 2026-07-23

### Added

- **`rate_limit` middleware** — fixed-window quotas advertised through
  the `RateLimit` / `RateLimit-Policy` structured fields
  (draft-ietf-httpapi-ratelimit-headers-11), with 429 + `Retry-After`
  on exhaustion. The quota partition `key` is a required callable
  (identifying a client is a trust-boundary decision the framework
  refuses to guess); the bundled `MemoryRateLimitStore` is per-process
  and swappable via the `RateLimitStore` protocol. Motivated by
  hayate-auth §9, whose brute-force defense mandates throttling
  `/api/auth/*`.
- **`parse_cookies` / `serialize_set_cookie` promoted to the public
  API.** hayate-auth's v0.1 dogfooding used both from the internal
  `hayate.cookies` module for session cookies; RFC 6265bis
  serialization belongs to the framework, so they are now exported,
  documented, and part of the freeze-audit surface (DESIGN §18).

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
