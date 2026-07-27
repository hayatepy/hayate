# Native Cloudflare Workers benchmark

This profile runs Hayate, three framework-free Python controls, and Hono
through the same locked local Wrangler/workerd runtime. The default Hayate
target uses `WorkerEntrypoint.fetch`; `hayate-global` and `raw-global`
explicitly enable Cloudflare's global-handler compatibility path to isolate
the current class RPC wrapper. ASGI, Uvicorn, and h11 are absent.

All targets implement the 67-route and four-scenario workload from the main
competitive benchmark. The profile records:

- the shared 14-case HTTP contract;
- local Wrangler/workerd startup to first response;
- deterministic dry-run upload size;
- warm throughput and p50/p99 latency;
- CPU time and peak RSS for the Wrangler descendant process tree.

Local process startup is not Cloudflare edge cold start. Shared-host
throughput is evidence, not a hard regression gate.

## Run

Prerequisites are CPython 3.12+, uv, Node.js 24, and npm on macOS or Linux.
All application and tool versions are committed in lockfiles.

Publication profile:

```sh
uv run --no-project python benchmarks/competitive/workers/runner.py all \
  --connections 20 \
  --duration 10 \
  --rounds 3 \
  --cold-rounds 5
```

Quick end-to-end check:

```sh
uv run --no-project python benchmarks/competitive/workers/runner.py all \
  --connections 5 \
  --duration 1 \
  --rounds 1 \
  --cold-rounds 2
```

`setup`, `verify`, and `run` subcommands are also available. Generated runtime
fixtures and default reports live under `.benchmark/competitive/`.

For a focused diagnostic run, select any declared subset without editing the
runner:

```sh
uv run --no-project python benchmarks/competitive/workers/runner.py all \
  --targets hayate-global,raw-global,hono \
  --connections 5 \
  --duration 1 \
  --rounds 1 \
  --cold-rounds 2
```

The current Hayate 0.15.1 publication-profile baseline is committed as
[raw JSON](results/2026-07-28-hayate-0.15.1-macos-arm64.json) and a
[Markdown summary](results/2026-07-28-hayate-0.15.1-macos-arm64.md). The
[Hayate 0.10.0 baseline](results/2026-07-26-macos-arm64.md) remains immutable
history.

[`current.toml`](current.toml) selects the result rendered into the public
benchmark page. Regenerate and verify that publication with:

```sh
uv run python benchmarks/competitive/workers/publish.py
uv run python benchmarks/competitive/workers/publish.py --check
```

## Fairness boundary

- All targets use Wrangler 4.114.0 and its exact workerd dependency.
- All use compatibility date `2026-07-01` with `--no-latest`.
- The `*-global` controls add `disable_python_no_global_handlers`. This is
  reported as a compatibility path, not Cloudflare's current default.
- Hono 4.12.32, workers-py 1.15.0, and workers-runtime-sdk 1.6.3 are
  exactly pinned.
- The Hayate fixture bundles a wheel built from the measured Git commit.
- Every Python target uses the same Wrangler `python_modules.exclude` list.
  It removes bytecode caches, distribution metadata, and ASGI/WSGI/AWS
  adapters that cannot execute in workerd. The compressed upload metric
  therefore measures runtime-relevant code instead of packaging debris.
  Excluding `*.dist-info` deliberately makes `importlib.metadata` unavailable
  inside these fixtures; application deployments that inspect package
  metadata should omit that exclusion.
- `raw-python` uses the SDK Request/Response wrappers. `raw-js` keeps the
  current class entrypoint but accesses its underlying JS objects directly.
  `raw-global` combines direct JS access with the compatibility handler.
  They are runtime/FFI boundaries, not frameworks.
- `pywrangler sync` happens during setup. Timed processes invoke Wrangler
  directly so Python dependency resolution is not counted as runtime startup.
- Every throughput sample gets a fresh Worker process plus 25 untimed warmup
  requests. Startup is measured separately. This isolates scenario CPU, RSS,
  and runtime state instead of carrying them into the next workload.
- Target and scenario order rotate between rounds.
- oha is the same checksum-pinned HTTP/1.1 load generator as the main suite.
