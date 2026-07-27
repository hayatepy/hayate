# Benchmarks

hayate publishes four benchmark boundaries:

1. A pinned, end-to-end competitive HTTP benchmark against FastAPI, Django,
   and Hono. It covers startup, cold start, dependency closure, deployment
   payload, throughput, and a shared HTTP contract.
2. A native Cloudflare Workers benchmark against Hono, with an SDK-only raw
   Python control. It removes ASGI and runs all targets on the same locked
   Wrangler/workerd runtime.
3. An in-process ASGI dispatch benchmark against Starlette. It isolates
   framework overhead by removing sockets and HTTP parsing.
4. A raw-ASGI transport profile inside the competitive suite. It executes the
   same four workloads on hayate's locked Uvicorn/asyncio/h11 environment and
   reports how much of that transport ceiling Hayate reaches.

Do not combine their request rates: they measure different boundaries.

The native Workers methodology and reproduction command live under
[`benchmarks/competitive/workers/`](https://github.com/hayatepy/hayate/tree/main/benchmarks/competitive/workers).
The default Hayate target enters through `WorkerEntrypoint.fetch`;
`hayate-global` separately measures Cloudflare's global-handler compatibility
path. ASGI, Uvicorn, and h11 are absent from both. Three framework-free Python
controls separate framework cost, FFI cost, and the current class-entrypoint
RPC wrapper. The local process-start metric is deliberately not labeled as a
deployed Cloudflare edge cold start.

## Native Cloudflare Workers benchmark

<!-- workers-current:start -->
### Current native Workers baseline (Hayate 0.15.1, 2026-07-27)

arm, macOS-26.5.1-arm64-arm-64bit-Mach-O, arm64, CPython 3.14.6, Node 24.18.0; Wrangler
4.114.0 / workerd 1.20260722.1 / local / compatibility-date runtime; 20 connections, 10
seconds per scenario, 3 rotating rounds. The source under test is commit `accb474`. All
72 throughput samples and 1,657,005 requests completed with zero errors, timeouts, or
non-2xx responses. Fresh process startup required 0 bounded retries; a second
consecutive failure would have failed the run.

| Target | Version | Local first response | gzip upload | Throughput | CPU s / 1k req | Peak tree RSS | HTTP contract |
|---|---:|---:|---:|---:|---:|---:|---:|
| Hayate class | 0.15.1 | 4,938.4 ms | 373.6 KiB | 1,904 req/s | 0.8772 | 1,839.2 MiB | 14/14 (100.0%) |
| Hayate global compatibility | 0.15.1 | 4,133.0 ms | 373.6 KiB | 2,896 req/s | 0.5519 | 1,913.1 MiB | 14/14 (100.0%) |
| Raw Python SDK class | 1.6.3 | 4,335.1 ms | 123.7 KiB | 1,878 req/s | 0.8939 | 1,431.1 MiB | 14/14 (100.0%) |
| Raw JS objects class | 1.6.3 | 3,998.0 ms | 124.3 KiB | 1,939 req/s | 0.8716 | 1,460.0 MiB | 14/14 (100.0%) |
| Raw JS objects global | Pyodide built-in | 4,491.7 ms | 124.3 KiB | 2,872 req/s | 0.5446 | 1,495.7 MiB | 14/14 (100.0%) |
| Hono | 4.12.32 | 550.9 ms | 38.0 KiB | 2,836 req/s | 0.5116 | 1,213.5 MiB | 12/14 (85.7%) |

Hayate measured at **98.17%** of the raw class-path control and **100.86%** of the raw
global-handler control. This isolates framework overhead from the Python Workers runtime
and entrypoint boundaries on the declared workload.

Against Hono, Hayate reached **67.14%** through the default class entrypoint and
**102.14%** through the global-handler compatibility path. The 2.14% global-path
difference is treated as shared-host throughput parity, not a hard victory or regression
threshold. Hono remained ahead on resource efficiency: Hayate global used 1.08x CPU per
request, 1.58x peak process-tree RSS, 9.83x compressed upload, and 7.50x local startup
time.

ASGI, Uvicorn, and h11 are absent from this profile. The default Hayate target uses
`WorkerEntrypoint.fetch`; the global target uses `disable_python_no_global_handlers`,
which is a compatibility path, not Cloudflare's current default. Local Wrangler startup
is not deployed edge cold start, raw controls are runtime/FFI boundaries rather than
frameworks, and the 14-case HTTP contract is the declared workload boundary rather than
a universal standards score.

- [Raw JSON](https://github.com/hayatepy/hayate/blob/main/benchmarks/competitive/workers/results/2026-07-28-hayate-0.15.1-macos-arm64.json)
- [Rendered summary](https://github.com/hayatepy/hayate/blob/main/benchmarks/competitive/workers/results/2026-07-28-hayate-0.15.1-macos-arm64.md)

Historical evidence remains immutable:

- [Hayate 0.10.0 previous release baseline](https://github.com/hayatepy/hayate/blob/main/benchmarks/competitive/workers/results/2026-07-26-macos-arm64.md)

This section is generated from `benchmarks/competitive/workers/current.toml` and the
selected raw report. Regenerate it with:

```sh
uv run python benchmarks/competitive/workers/publish.py
```
<!-- workers-current:end -->

## Competitive HTTP benchmark

The implementations, exact dependency locks, methodology, raw-result schema,
and one-command reproduction instructions live in
[`benchmarks/competitive/`](https://github.com/hayatepy/hayate/tree/main/benchmarks/competitive).
The full publication profile is:

```sh
python3 benchmarks/competitive/runner.py all \
  --connections 50 \
  --duration 10 \
  --rounds 3 \
  --cold-rounds 7
```

Python targets run on the same Uvicorn asyncio + h11 transport. Hono runs on
its official Node adapter. The load generator is the same checksum-pinned oha
1.15.0 binary for every target. Raw JSON records all samples, resolved
transitive versions, Git commit, CPU, operating system, and configuration.

The 14-point HTTP contract is a common-workload compatibility rate, not a
universal standards score. hayate's WPT-based URL and URLPattern results are
reported on the [conformance page](conformance.md); unsupported public APIs in
other frameworks are not converted into artificial zeroes.

Framework capability breadth is tracked separately in the dated,
source-backed [competitive capability matrix](capabilities.md). It has no
weighted score and keeps Django's full-stack strengths and Hono's
JavaScript-edge strengths visible.

The monthly and manually dispatchable
[Competitive benchmark workflow](https://github.com/hayatepy/hayate/actions/workflows/competitive-benchmark.yml)
uploads the raw JSON and Markdown summary. Shared-runner measurements are not
used as a hard regression gate because host contention is uncontrolled.

<!-- competitive-current:start -->
### Current released baseline (Hayate 0.15.1, 2026-07-27)

Apple M2 Pro, macOS 26.5.1, arm64, CPython 3.14.6, Node 24.18.0; 50 connections, 10
seconds per scenario, 3 rotating rounds. The source under test is commit `561bcf0`. All
60 throughput samples completed with zero errors, timeouts, or non-2xx responses.

| Framework | Version | App import | Cold start | Production packages | gzip payload | Throughput geo mean | HTTP contract |
|---|---:|---:|---:|---:|---:|---:|---:|
| Hayate | 0.15.1 | 96.7 ms | 149.0 ms | 5 | 298.1 KiB | 14,906 req/s | 14/14 (100.0%) |
| FastAPI | 0.140.0 | 454.6 ms | 471.4 ms | 13 | 2,802.2 KiB | 10,086 req/s | 12/14 (85.7%) |
| Django | 6.0.7 | 373.4 ms | 392.6 ms | 6 | 5,147.2 KiB | 2,557 req/s | 12/14 (85.7%) |
| Hono | 4.12.32 | 55.3 ms | 61.3 ms | 2 | 281.5 KiB | 59,187 req/s | 12/14 (85.7%) |

On this workload, Hayate delivered 1.48x FastAPI's and 5.83x Django's throughput.
FastAPI and Django took 3.16x and 2.64x as long to cold-start. Hono delivered 3.97x
Hayate's throughput, and Hayate took 2.43x as long to cold-start.

Hayate's runtime-excluded compressed payload was 5.9% larger than Hono's official Node
stack while using 3 more production packages. FastAPI's and Django's payloads were 9.40x
and 17.27x Hayate's.

The same run measured the raw Uvicorn/asyncio/h11 workload ceiling at 16,765 req/s.
Hayate reached **88.9%** of that ceiling overall and 86.0% to 94.0% across the four
workloads. Hono was 3.53x faster than raw Uvicorn itself, so most of the remaining Hono
gap belongs to the runtime/transport boundary rather than Hayate's framework core.

The full reports contain every sample, latency percentile, resolved package version, and
machine field. These numbers are a reproducible baseline, not a claim about all
applications or hardware.

- [Raw JSON](https://github.com/hayatepy/hayate/blob/main/benchmarks/competitive/results/2026-07-28-hayate-0.15.1-macos-arm64.json)
- [Rendered summary](https://github.com/hayatepy/hayate/blob/main/benchmarks/competitive/results/2026-07-28-hayate-0.15.1-macos-arm64.md)

Historical evidence remains immutable:

- [Hayate 0.13.0 previous release baseline](https://github.com/hayatepy/hayate/blob/main/benchmarks/competitive/results/2026-07-27-hayate-0.13-macos-arm64.md)
- [Hayate 0.12.1 optimized baseline](https://github.com/hayatepy/hayate/blob/main/benchmarks/competitive/results/2026-07-27-asgi-optimized-macos-arm64.md)
- [pre-optimization baseline](https://github.com/hayatepy/hayate/blob/main/benchmarks/competitive/results/2026-07-27-macos-arm64.md)

This section is generated from `benchmarks/competitive/current.toml` and the selected
raw report. Regenerate it with:

```sh
uv run python benchmarks/competitive/publish.py
```
<!-- competitive-current:end -->

The suite also measures a raw ASGI implementation of the same four workloads
inside hayate's locked Python environment. This separates framework overhead
from the Uvicorn/h11 versus Node transport difference; the raw target is not
ranked as a framework and is excluded from startup and payload comparisons.

## In-process ASGI dispatch

This historical benchmark measures hayate against Starlette with no sockets
or HTTP parsing. Both frameworks are driven directly through their ASGI
callable with a no-op transport and a fresh scope per request.

Run:

```sh
uv run --group bench python benchmarks/bench.py
```

## Results (2026-07-22, hayate 0.6.0, Tier 1 + Tier 2 accelerator)

Apple Silicon (arm64), CPython 3.14.6, hayate 0.6.0 with hayate-accel,
starlette 1.3.1. N=10,000 per round, best of 3 rounds.

| Scenario | hayate req/s | Starlette req/s | Ratio |
|---|---:|---:|---:|
| static-text | 243,782 | 192,686 | **1.27x** |
| dynamic-json | 170,337 | 154,827 | **1.10x** † |
| many-routes(64) | 200,097 | 52,190 | **3.83x** |
| middleware(2) | 155,975 | 3,512 | 44.41x * |

† 0.6.0's segment-trie router is flat at ~0.95 µs/match regardless of
route count (many-routes went 1.93x → 3.83x), but a *single* dynamic
route is the linear scan's absolute best case (one C-regex call,
~0.5 µs) — this scenario gave back ~8%. Real apps with more than a
couple of routes come out ahead; the trade-off and the rejected
alternatives are recorded in DESIGN §14.4.

\* Starlette's stock middleware mechanism (``BaseHTTPMiddleware``) has a
well-known high overhead (a task plus stream re-wrapping per request);
hand-written raw-ASGI middleware would narrow this. hayate's onion
composition adds no tasks, so the number is real but the comparison is
of each framework's *standard* middleware story.

Without the accelerator (pure Python, Tier 0+1), dynamic-json measures
0.99x — parity; the Rust JSON encoder buys the remaining +23%.

The measured floor (a raw ASGI function doing nothing but two ``send``
calls) is ~1.96M req/s (0.51µs/req); the "framework tax" is what both
frameworks add on top.

## Progression (static-text / dynamic-json vs Starlette)

| Stage | static | dynamic-json |
|---|---:|---:|
| v0.1 initial (eager Fetch objects) | 0.43x | 0.44x |
| + trusted adapter fast paths | 0.96x | 0.86x |
| + Tier 1 lazy materialization | 1.20x | 0.99x |
| + Tier 2 Rust JSON encoder | 1.20x | **1.22x** |

## The tiers (DESIGN.md §14)

- **Tier 1 (pure Python, everywhere incl. Pyodide)**: header bytes kept
  wire-native and decoded lazily; bodyless requests carry a null body
  per Fetch (no stream, no signal); per-request allocations created on
  first use; middleware chains precomputed when unscoped (Stage 2).
- **Tier 2 (`hayate-accel`, Rust/PyO3, abi3 ≥3.12)**: compact JSON
  encoder behaviorally identical to
  ``json.dumps(..., ensure_ascii=False, separators=(",", ":"))`` for
  supported types; anything else raises ``TypeError`` and falls back to
  the stdlib. Since 0.2.0 it also accelerates multipart parsing: the
  boundary scan uses SIMD substring search (``memchr::memmem``) and
  copies each payload once — ``parse_multipart`` on a 10.5 MB body with
  two file parts drops from 5.7 ms to 0.5 ms (**11x**, Apple Silicon).
  Semantic parsing stays in the pure-Python path; the two splitters are
  pinned identical by parity tests. Build locally:

  ```sh
  uv run --with maturin maturin build --release -m accel/Cargo.toml -o dist-accel
  uv pip install dist-accel/*.whl
  ```

Numbers shift with hardware and Python versions; re-run locally before
drawing conclusions.
