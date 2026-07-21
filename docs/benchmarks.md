# Benchmarks

In-process ASGI dispatch benchmark against Starlette — framework
overhead only (no sockets, no HTTP parsing). Both frameworks are driven
directly through their ASGI callable with a no-op transport and a fresh
scope per request.

Run:

```sh
uv run --group bench python benchmarks/bench.py
```

## Results (2026-07-22)

Apple Silicon (arm64), CPython 3.14.6, hayate 0.1.0.dev0,
starlette 1.3.1. N=10,000 per round, best of 3 rounds.

| Scenario | hayate req/s | Starlette req/s | Ratio |
|---|---:|---:|---:|
| static-text | 182,691 | 191,088 | 0.96x |
| dynamic-json | 131,052 | 153,135 | 0.86x |
| many-routes(64) | 92,568 | 52,515 | **1.76x** |

Geometric mean: **1.13x** — the DESIGN.md §14 bar ("Starlette parity or
better as pure Python") is met.

## Reading the numbers

- Fixed per-request overhead is on par with Starlette (static-text).
  hayate materializes a WHATWG ``URL`` and a Fetch ``Request`` on every
  request — that model *is* the product — and keeps it nearly free via
  trusted adapter fast paths (``URL._from_server``,
  ``Headers._from_wire``: server-supplied values skip re-validation,
  semantics unchanged).
- At realistic route counts the static-dict + per-method precompiled
  regex router pulls clearly ahead (1.76x at 64 routes).
- dynamic-json trails slightly (0.86x); the residual gap is route-param
  handling and response assembly. Revisit in the evidence-driven router
  pass (DESIGN.md §6.2) if it matters in practice.

Numbers shift with hardware and Python versions; re-run locally before
drawing conclusions.
