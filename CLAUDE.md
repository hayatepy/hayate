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
uv run pytest -q                  # 258 passing; ~80 skips are *counted* wpt out-of-scope cases
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
- **pyo3 must stay ≥ 0.26**: 0.23 crashes at runtime on Python 3.14.
- **GitHub `macos-13` (Intel) runners are retired**; Intel wheels are
  cross-compiled from `macos-latest` (`x86_64-apple-darwin`).
- ASGI guarantees lowercase header names; `Headers._from_wire` relies on it.

## Current state / next steps (as of 2026-07-22)

- Published: **hayate 0.3.1 on PyPI**; docs site live; repository public
  under the `hayatepy` org (maintainer: Yusuke Hayashi, MIT).
- v0.1–v0.3 milestone acceptance criteria are all met, including
  "same app runs unchanged on uvicorn and Workers" (verified on local
  workerd — see research §5).
- **Pending manual step**: hayate-accel publish. All wheels build in CI;
  PyPI needs a pending publisher (project `hayate-accel`, owner `hayatepy`,
  repo `hayate`, workflow `release-accel.yml`, environment `pypi`), then
  rerun the failed publish job.
- Open engineering work: research §5 unchecked items (streaming bridge,
  AbortSignal bridge, Durable Object mount, WebSocket on Workers,
  production deploy) and DESIGN §18 v1.0 criteria.
