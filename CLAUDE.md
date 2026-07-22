# CLAUDE.md

Guidance for AI agents (and humans) working on hayate.

## Orientation

hayate is a web-standards-first Python web framework inspired by Hono: the
Fetch API model (WHATWG Request / Response / Headers / URL / URLPattern) is
the user-facing surface; WSGI/ASGI are adapter details.

- **Read [DESIGN.md](DESIGN.md) first** (Japanese). Every design decision,
  its rationale, and the rejected alternatives live there — it is the
  authority on "why". Milestones and settled decisions are in §18.
- [docs/research/cloudflare.md](docs/research/cloudflare.md): Workers
  platform research and the on-workerd verification log (§5 = open items).
- Measured claims: [docs/conformance.md](docs/conformance.md),
  [docs/benchmarks.md](docs/benchmarks.md).

## Non-negotiable rules

1. **English** for everything in code and public docs (docstrings, comments,
   README, docs/). Internal design memos (DESIGN.md, docs/research/) are
   Japanese. This repository rule overrides any personal/global instruction
   to write documentation in Japanese.
2. **Standards-first gate**: no core feature without a WHATWG/IETF
   counterpart (DESIGN §2). Divergences must be *documented subsets*,
   measured by the wpt suites — never silent.
3. **Zero-dependency core.** Schema libraries, the Rust accelerator, and
   servers stay optional and outside the core.
4. **KISS/YAGNI, evidence-driven**: single code path; profile before
   optimizing (DESIGN §14 records how each optimization was justified).
5. **Conformance ratchets only go up**: `MIN_PASS` in
   `tests/test_wpt_*.py` may be raised, never lowered.
6. Naming: semantics from the standard, spelling per PEP 8
   (`searchParams` → `search_params`, `getSetCookie()` → `set_cookie_list()`).

## Commands

```sh
uv run pytest -q                  # 254 passing on 3.14 (283 with accel); ~80 skips are *counted* wpt out-of-scope cases
uv run ruff check --fix src tests benchmarks && uv run ruff format src tests benchmarks
uv run --group bench python benchmarks/bench.py       # vs Starlette; "floor" = raw ASGI fn
uv sync --group docs && uv run mkdocs build --strict  # site: https://hayatepy.github.io/hayate/
uv run --with maturin maturin build --release -m accel/Cargo.toml -o dist-accel \
  && uv pip install dist-accel/*.whl                  # Tier 2 accelerator (then rerun pytest)
cd examples/workers && uv sync && uv run pywrangler dev   # local workerd
```

## Releases

- **hayate**: bump the version in *both* `pyproject.toml` and
  `src/hayate/__init__.py`, update `CHANGELOG.md`, tag `vX.Y.Z`, push the
  tag. `release.yml` tests, builds, and publishes to PyPI via Trusted
  Publishing (environment `pypi`).
- **hayate-accel**: tag `accel-vX.Y.Z` (or run "Release accel" via
  workflow_dispatch) → `release-accel.yml` builds linux x64/arm64,
  macOS arm64 + x86_64 (cross-compiled), windows, sdist, then publishes.

## Known traps (learned on real infrastructure)

- **pywrangler vendors from `pylock.toml` resolved against PyPI** —
  `tool.uv.sources` path dependencies are ignored. To verify adapter
  changes on workerd, release to PyPI first (or hand-copy into the
  generated `python_modules/`).
- **On workerd the fetch handler receives workers-py's Python Request
  wrapper** (`bytes()` / `headers.items()`), not a raw JS proxy
  (`arrayBuffer()` / `entries()`). The adapter supports both shapes;
  `tests/test_workers_adapter.py` pins them. Mocks alone missed this.
  The wrapper's exact surface is pinned from the SDK source (workerd
  `src/pyodide/internal/workers-api`): the raw JS request sits on
  `js_object`, `body` forwards the JS ReadableStream, and `signal`
  exists *only* on `js_object`. `workers.Response` accepts a
  `ReadableStream` body (`RESPONSE_ACCEPTED_TYPES`).
- **pyo3 must stay ≥ 0.26**: 0.23 crashes at runtime on Python 3.14.
  Currently on 0.29 (0.28 renamed `downcast` → `cast`).
- **GitHub `macos-13` (Intel) runners are retired**; Intel wheels are
  cross-compiled from `macos-latest` (`x86_64-apple-darwin`).
- ASGI guarantees lowercase header names; `Headers._from_wire` relies on it.
- **workerd registers Durable Object classes by `cls.__name__`**, not by
  the entry-module attribute name (workerd `introspection.py`). With
  `@to_durable_object` the factory's name is the class name and must
  match wrangler.toml `class_name`; a unit test pins this.
- **Workers websocket binary frames arrive as `Blob` by default** (async
  readers only) — the adapter sets `binaryType = "arraybuffer"` on
  accept. A bare `ArrayBuffer` proxy is *not* converted by `to_py()`
  (TypedArray views are); use `to_bytes()` (JsBuffer API) — `_js_bytes`
  centralizes this.
- **ty evaluated 2026-07-22 (0.0.62): not adopted.** 23 diagnostics, mostly
  false positives on the Fetch-standard `bytes()` method name and on
  guarded platform imports (`js`, `workers`, `pyodide`, `compression`).
  The standard surface is not renamed to satisfy a 0.0.x checker;
  revisit at ty 1.0 (a few argument-type findings may be real).

## Current state / next steps (as of 2026-07-22)

- Published: **hayate 0.6.0** and **hayate-accel 0.2.0** on PyPI; docs
  site live; repository public under the `hayatepy` org (maintainer:
  Yusuke Hayashi, MIT).
- 0.6.0: **segment-trie router** (static dict → trie → regex tail;
  0.95 µs flat at any route count, many-routes(64) 3.83x Starlette;
  registration order preserved by index — tests/test_router.py pins
  it) and **WHATWG IPv4/IPv6 canonicalization + %2e dot-segments**,
  which raised the URL conformance ratchet **202 → 246/306 (80.4%)**
  with zero dependencies. The remaining URL gap is the demand-gated
  IDNA pipeline: the rejection error and docs point at issue #2, which
  collects use cases; ~310 KiB UTS-46 tables is the known cost.
- 0.5.0 added **`workers.forward(c, fetcher)`** — platform-response
  passthrough. Because nothing is rebuilt, a websocket upgrade passes
  *through* the outer app into a Durable Object's own `@app.ws()`
  route; verified on a local workerd and in production over wss. This
  closed the boundary-impedance gap recorded in DESIGN §14.4. Also:
  measured micro-optimizations (wire-encode memo 114→41ns/pair,
  `Headers.get` fast path, shared empty params) and measured
  *rejections* (header interning, flat-alternation router 9x worse,
  per-method route indexes) — every number is in §14.4 so the
  questions stay settled.
- 0.4.1 thinned the Workers FFI boundary (trusted URL split, trusted
  header pairs, null-body skip, one-crossing response headers) and
  added the Rust multipart splitter (SIMD memmem, 11x on a 10.5 MB
  body; parity with the pure path pinned by tests). Durable Object
  storage persists across redeploys (counter 3 → 4 → 5).
- The public-API audit ran (41 exported names, all documented; audit
  procedure and freeze list in DESIGN §18) and the monthly report-only
  `wpt refresh` workflow guards against silent spec drift (first
  dispatch: green against latest upstream data).
- **research §5 is fully verified — every item closed**, on a local
  workerd *and* in production (`pywrangler deploy`, account-owned URL
  recorded in research §5): websocket over `WebSocketPair` (same
  `@app.ws()` handler as ASGI, text/binary/clean-close over wss),
  `@to_durable_object` mounts with persistent per-name storage,
  production SSE TTFB 53 ms vs 1.55 s total, and the deterministic FFI
  proxy lifecycle held RSS flat over 3,200 requests (35.4 → 35.9 MB,
  zero errors). All numbers and the SDK/workerd source references live
  in research §5.
- v0.1–v0.4 milestone acceptance criteria are all met. **v1.0
  acceptance criteria are now defined in DESIGN §18** (conformance
  ratchets, reproducible 3-runtime verification, benchmark gate,
  SECURITY.md + support policy — done, and a ≥3-month external-usage
  window from the 2026-07-22 0.3.0 release, so v1.0 is decidable
  2026-10 at the earliest).
- Open engineering work: keep criteria 1–4 green on each release; watch
  issues/feedback for the criterion-5 window; platform extensions
  (WebSocket hibernation API, RPC entrypoints) stay out until evidence
  demands them.
