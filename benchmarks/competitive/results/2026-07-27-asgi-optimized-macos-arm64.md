# Competitive benchmark result

- Commit: `697b20d2b8b4bc05437124bb7aff4e81ef1e3c5d`
- Measured: `2026-07-27T08:42:45.386314+00:00`
- Machine: Apple M2 Pro / arm64 / macOS-26.5.1-arm64-arm-64bit-Mach-O
- Load: oha 1.15.0, 50 connections, 10s x 3 rounds

| Framework | Version | App import (ms) | Server ready (ms) | Cold start (ms) | Prod. packages | gzip payload (KiB) | Throughput geo mean (req/s) | HTTP contract |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| hayate | 0.12.1 | 84.8 | 113.2 | 114.2 | 5 | 289.8 | 14,451 | 14/14 (100.0%) |
| fastapi | 0.140.0 | 406.1 | 428.4 | 429.3 | 13 | 2,802.2 | 9,578 | 12/14 (85.7%) |
| django | 6.0.7 | 346.1 | 351.7 | 352.9 | 6 | 5,147.2 | 2,883 | 12/14 (85.7%) |
| hono | 4.12.32 | 56.3 | 59.3 | 64.9 | 2 | 281.5 | 60,424 | 12/14 (85.7%) |

## Throughput by workload

| Framework | Static text | Dynamic JSON | 64 routes | JSON echo |
|---|---:|---:|---:|---:|
| hayate | 15,500 | 14,800 | 15,280 | 12,439 |
| fastapi | 11,405 | 9,837 | 7,961 | 9,423 |
| django | 2,983 | 2,989 | 2,715 | 2,852 |
| hono | 65,968 | 59,770 | 64,531 | 52,390 |

## Python transport profile

The raw ASGI target runs the same four workloads in hayate's exact
locked Uvicorn/asyncio/h11 environment. It is a transport ceiling,
not a fifth framework or a separately tuned server.

| Boundary | Geo mean | Static text | Dynamic JSON | 64 routes | JSON echo |
|---|---:|---:|---:|---:|---:|
| Raw ASGI (req/s) | 16,010 | 17,054 | 16,303 | 16,810 | 14,057 |
| Hayate / raw efficiency | 90.3% | 90.9% | 90.8% | 90.9% | 88.5% |

The HTTP contract is not a universal Web-standards score. It checks the
same observable HTTP behavior for these four workload apps, including
RFC 9110 method handling and HEAD semantics. hayate's WPT results are
reported separately in `docs/conformance.md`.
