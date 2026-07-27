# Competitive multipart upload result

- Commit: `2523ff6ebcc5aba86e90357a8ba1b1342b67d610`
- Measured: `2026-07-27T11:09:32.436813+00:00`
- Machine: Apple M2 Pro / arm64 / macOS-26.5.1-arm64-arm-64bit-Mach-O
- Contract: one multipart file, 64 KiB application reads, SHA-256 verification

| Framework | Size | Requests/s | Payload MiB/s | Peak RSS MiB | Logical temp MiB/request |
|---|---:|---:|---:|---:|---:|
| hayate | 1-mib | 840.272 | 840.3 | 37.6 | 0.0 |
| hayate | 64-mib | 9.278 | 593.8 | 38.1 | 64.0 |
| fastapi | 1-mib | 795.497 | 795.5 | 58.0 | 0.0 |
| fastapi | 64-mib | 6.399 | 409.5 | 58.2 | 64.0 |
| django | 1-mib | 348.979 | 349.0 | 54.3 | 1.0 |
| django | 64-mib | 8.304 | 531.4 | 51.2 | 64.0 |
| hono | 1-mib | 427.712 | 427.7 | 127.4 | 0.0 |
| hono | 64-mib | 14.558 | 931.7 | 539.2 | 0.0 |

Peak RSS is the fresh server process maximum reported by `/usr/bin/time`,
so it includes the framework/runtime baseline and upload handling. Logical
temporary-disk bytes describe the accepted file bytes held by each
framework's disk-backed upload object, not filesystem allocation blocks.
Hono reports zero because its Fetch `FormData` path remains memory-backed;
interpret that together with peak RSS rather than as an isolated win.
