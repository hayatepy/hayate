# Benchmarks

hayate publishes two separate suites:

1. A pinned, end-to-end competitive HTTP benchmark against FastAPI, Django,
   and Hono. It covers startup, cold start, dependency closure, deployment
   payload, throughput, and a shared HTTP contract.
2. An in-process ASGI dispatch benchmark against Starlette. It isolates
   framework overhead by removing sockets and HTTP parsing.

Do not combine their request rates: they measure different boundaries.

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
its official Node adapter. The load generator is the same pinned autocannon
installation for every target. Raw JSON records all samples, resolved
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

Apple M2 Pro, macOS 26.5.1, arm64, Python 3.14.6, Node 26.5.0;
50 connections, 10 seconds per scenario, three rotating rounds. The source
under test is commit `b616c49`; every one of the 48 throughput samples
completed with zero errors, timeouts, or non-2xx responses.

| Framework | Version | App import | Cold start | Production packages | gzip payload | Throughput geo mean | HTTP contract |
|---|---:|---:|---:|---:|---:|---:|---:|
| **hayate** | 0.10.0 | **61.1 ms** | **130.3 ms** | **5** | **280.3 KiB** | **14,016 req/s** | **14/14 (100%)** |
| FastAPI | 0.140.0 | 204.2 ms | 244.1 ms | 13 | 2,802.1 KiB | 9,861 req/s | 12/14 (85.7%) |
| Django | 6.0.7 | 132.0 ms | 168.2 ms | 6 | 5,147.1 KiB | 2,740 req/s | 12/14 (85.7%) |
| Hono | 4.12.32 | **56.4 ms** | **66.6 ms** | **2** | 281.5 KiB | **64,794 req/s** | 12/14 (85.7%) |

On this workload, hayate delivered 1.42x FastAPI's and 5.12x Django's
throughput. Its cold start was 1.87x faster than FastAPI's and 1.29x faster
than Django's. Hono remained 4.62x faster in throughput and 1.96x faster at
cold start. hayate's runtime-excluded compressed payload was approximately
the same size as Hono's official Node stack, while using three more production
packages.

The full [raw report](https://github.com/hayatepy/hayate/blob/main/benchmarks/competitive/results/2026-07-26-macos-arm64.json)
and [rendered summary](https://github.com/hayatepy/hayate/blob/main/benchmarks/competitive/results/2026-07-26-macos-arm64.md)
contain every sample, latency percentile, resolved package version, and
machine field. These numbers are a reproducible baseline, not a claim about
all applications or hardware.

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
