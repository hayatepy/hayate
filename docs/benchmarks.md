# Benchmarks

In-process ASGI dispatch benchmark against Starlette — framework
overhead only (no sockets, no HTTP parsing). Both frameworks are driven
directly through their ASGI callable with a no-op transport and a fresh
scope per request.

Run:

```sh
uv run --group bench python benchmarks/bench.py
```

## Results (2026-07-22, after the Tier 1 "lazy materialization" pass)

Apple Silicon (arm64), CPython 3.14.6, hayate 0.1.0.dev0,
starlette 1.3.1. N=10,000 per round, best of 3 rounds.

| Scenario | hayate req/s | Starlette req/s | Ratio |
|---|---:|---:|---:|
| static-text | 236,512 | 196,773 | **1.20x** |
| dynamic-json | 150,277 | 152,564 | 0.99x |
| many-routes(64) | 102,100 | 52,168 | **1.96x** |

Geometric mean: **1.33x**. For reference, the measured floor (a raw
ASGI function doing nothing but two ``send`` calls) is ~1.96M req/s
(0.51µs/req); the "framework tax" is what both frameworks add on top.

Progression of the static-text scenario:

| Stage | req/s | vs Starlette |
|---|---:|---:|
| v0.1 initial (eager Fetch objects) | 82,986 | 0.43x |
| + trusted adapter fast paths (`URL._from_server`, `Headers._from_wire`) | 182,691 | 0.96x |
| + Tier 1 lazy materialization | 236,512 | 1.20x |

## What Tier 1 does (DESIGN.md §14)

CPython is an interpreter: per-request cost is linear in allocations +
calls + bytecode. Tier 1 removes work for things a handler never
observes, without changing Fetch semantics:

- Header pairs stay as the server's raw ``bytes`` and decode to ``str``
  lazily on first access (ASGI guarantees lowercase names).
- Bodyless requests (no ``content-length`` / ``transfer-encoding``)
  carry a null body per Fetch — no stream, no ``AbortSignal``.
- ``request.signal``, ``c.set()`` storage, ``c.header()`` staging, and
  the ``wait_until`` ``ExecutionContext`` are allocated on first use;
  deferred work rides on the response and is drained after delivery.
- Middleware-free routes skip the onion dispatch closures entirely.

## Next levers (DESIGN.md §14.2)

- Precomposed middleware chains (Stage 2) — helps middleware-heavy apps.
- Tier 2 native accelerator (Rust via maturin, pure-Python fallback,
  emscripten wheels for Workers) once profiles identify a target worth
  the build-chain cost.

Numbers shift with hardware and Python versions; re-run locally before
drawing conclusions.
