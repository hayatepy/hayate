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
Hayate enters through `WorkerEntrypoint.fetch`, so ASGI, Uvicorn, and h11 are
absent. The raw target separates framework cost from the Python runtime/SDK
boundary. The local process-start metric is deliberately not labeled as a
deployed Cloudflare edge cold start.

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

The monthly and manually dispatchable
[Competitive benchmark workflow](https://github.com/hayatepy/hayate/actions/workflows/competitive-benchmark.yml)
uploads the raw JSON and Markdown summary. Shared-runner measurements are not
used as a hard regression gate because host contention is uncontrolled.

### Recorded baseline (2026-07-26)

Apple M2 Pro, macOS 26.5.1, arm64, CPython 3.14.6, Node 26.5.0;
50 connections, 10 seconds per scenario, three rotating rounds. The source
under test is commit `ecd091d`; every one of the 60 throughput samples
completed with zero errors, timeouts, or non-2xx responses.

| Framework | Version | App import | Cold start | Production packages | gzip payload | Throughput geo mean | HTTP contract |
|---|---:|---:|---:|---:|---:|---:|---:|
| **hayate** | 0.10.0 | 79.4 ms | **114.1 ms** | **5** | **280.3 KiB** | **13,438 req/s** | **14/14 (100%)** |
| FastAPI | 0.140.0 | 198.7 ms | 214.7 ms | 13 | 2,802.1 KiB | 9,631 req/s | 12/14 (85.7%) |
| Django | 6.0.7 | 141.6 ms | 151.0 ms | 6 | 5,147.1 KiB | 2,805 req/s | 12/14 (85.7%) |
| Hono | 4.12.32 | **53.6 ms** | **61.8 ms** | **2** | 281.5 KiB | **63,069 req/s** | 12/14 (85.7%) |

On this workload, hayate delivered 1.40x FastAPI's and 4.79x Django's
throughput. Its cold start was 1.88x faster than FastAPI's and 1.32x faster
than Django's. Hono remained 4.69x faster in throughput and 1.85x faster at
cold start. hayate's runtime-excluded compressed payload was approximately
the same size as Hono's official Node stack, while using three more production
packages.

The same run measured the raw Uvicorn/asyncio/h11 workload ceiling at
16,094 req/s. Hayate reached 83.5% of that ceiling overall and 81.2–87.1%
across the four workloads. Hono was 3.92x faster than raw Uvicorn itself, so
most of the remaining Hono gap belongs to the runtime/transport boundary
rather than Hayate's framework core.

The full [raw report](https://github.com/hayatepy/hayate/blob/main/benchmarks/competitive/results/2026-07-26-macos-arm64.json)
and [rendered summary](https://github.com/hayatepy/hayate/blob/main/benchmarks/competitive/results/2026-07-26-macos-arm64.md)
contain every sample, latency percentile, resolved package version, and
machine field. These numbers are a reproducible baseline, not a claim about
all applications or hardware.

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
