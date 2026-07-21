# Benchmarks

In-process ASGI dispatch benchmark against Starlette — framework
overhead only (no sockets, no HTTP parsing). Both frameworks are driven
directly through their ASGI callable with a no-op transport and a fresh
scope per request.

Run:

```sh
uv run --group bench python benchmarks/bench.py
```

## Results (2026-07-22, Tier 1 + Tier 2 accelerator)

Apple Silicon (arm64), CPython 3.14.6, hayate 0.2.0.dev0 with
hayate-accel, starlette 1.3.1. N=10,000 per round, best of 3 rounds.

| Scenario | hayate req/s | Starlette req/s | Ratio |
|---|---:|---:|---:|
| static-text | 236,323 | 197,388 | **1.20x** |
| dynamic-json | 187,466 | 153,280 | **1.22x** |
| many-routes(64) | 100,826 | 52,356 | **1.93x** |
| middleware(2) | 149,331 | 3,403 | 43.89x * |

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
  the stdlib. Build locally:

  ```sh
  uv run --with maturin maturin build --release -m accel/Cargo.toml -o dist-accel
  uv pip install dist-accel/*.whl
  ```

Numbers shift with hardware and Python versions; re-run locally before
drawing conclusions.
