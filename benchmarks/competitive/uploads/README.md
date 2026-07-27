# Competitive multipart upload benchmark

This profile sends the same single-file `multipart/form-data` request to
Hayate, FastAPI, Django, and Hono. Every endpoint reads the accepted file in
64 KiB application chunks, computes SHA-256, and returns the observed size,
digest, and logical temporary-file bytes.

It records:

- completed requests and payload bytes per second;
- fresh server-process peak RSS from `/usr/bin/time`;
- logical bytes held by disk-backed upload storage per request;
- every raw round, exact framework/runtime versions, lock hashes, machine
  metadata, configuration, and Git commit.

## Run

Prerequisites match the parent competitive suite: CPython 3.12+, `uv`, and
Node.js 24. macOS and Linux are supported because their `/usr/bin/time`
implementations expose process peak RSS.

```sh
python3 benchmarks/competitive/uploads/runner.py all \
  --rounds 3 \
  --small-requests 12 \
  --small-connections 2 \
  --large-requests 3 \
  --large-connections 1
```

The two publication workloads contain exactly 1 MiB and 64 MiB of deterministic
file content. `verify` installs the locked targets and sends a 2 MiB file
through every implementation, exercising native disk spill in the three Python
frameworks and the memory-backed Fetch path in Hono.

FastAPI's upload-only `python-multipart` dependency is a locked optional extra,
so it does not change the dependency count or payload of the parent non-upload
benchmark. The four upload apps are separate modules for the same reason.

## Interpretation

Peak RSS includes each framework and runtime baseline as well as request
handling. Temporary-disk bytes are logical accepted-file bytes reported from
the framework's upload storage state, not allocated filesystem blocks. Hayate,
FastAPI, and Django use a 1 MiB native memory threshold; Hono's Fetch
`FormData` route reports zero temporary bytes because it stays memory-backed.
Zero disk use is therefore not an isolated win and must be interpreted with
peak RSS.

The benchmark verifies complete reads by digest, but it is not a storage,
database, antivirus, extraction, or reverse-proxy benchmark. Results describe
the committed versions, workload, machine, and concurrency—not universal
framework performance.
