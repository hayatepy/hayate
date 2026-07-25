# Native Cloudflare Workers benchmark

This profile runs Hayate, a framework-free Python control, and Hono through
the same locked local Wrangler/workerd runtime. Hayate uses
`WorkerEntrypoint.fetch` directly: ASGI, Uvicorn, and h11 are absent.

All three targets implement the 67-route and four-scenario workload from the main
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

## Fairness boundary

- All three targets use Wrangler 4.114.0 and its exact workerd dependency.
- Both use compatibility date `2026-07-01` with `--no-latest`.
- Hono 4.12.32, workers-py 1.15.0, and workers-runtime-sdk 1.6.3 are
  exactly pinned.
- The Hayate fixture bundles a wheel built from the measured Git commit.
- The raw Python target implements the workload with only
  `workers-runtime-sdk`; it is a Python runtime/SDK boundary, not a framework.
- `pywrangler sync` happens during setup. Timed processes invoke Wrangler
  directly so Python dependency resolution is not counted as runtime startup.
- Every throughput sample gets a fresh Worker process plus 25 untimed warmup
  requests. Startup is measured separately. This isolates scenario CPU, RSS,
  and runtime state instead of carrying them into the next workload.
- Target and scenario order rotate between rounds.
- oha is the same checksum-pinned HTTP/1.1 load generator as the main suite.
