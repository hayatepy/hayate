# Competitive HTTP benchmark

This suite runs the same observable workload on hayate, FastAPI, Django,
and Hono. It measures startup, production dependency count, compressed
deployment payload, cold start, HTTP throughput, and a shared HTTP
contract. Every application and load-tool version is pinned by a committed
`uv.lock` or `package-lock.json`.

## Run

Prerequisites:

- CPython 3.12 or newer
- [uv](https://docs.astral.sh/uv/)
- Node.js 24 and npm

Run the publication profile:

```sh
python3 benchmarks/competitive/runner.py all \
  --connections 50 \
  --duration 10 \
  --rounds 3 \
  --cold-rounds 7
```

The raw JSON and a Markdown summary are written under
`.benchmark/competitive/` by default. A quick end-to-end check is:

```sh
python3 benchmarks/competitive/runner.py all \
  --connections 10 \
  --duration 1 \
  --rounds 1 \
  --cold-rounds 2
```

`setup`, `verify`, and `run` subcommands are also available. `run` reuses
the isolated environments created by `setup`.

The first publication-profile baseline is committed as
[raw JSON](results/2026-07-26-macos-arm64.json) and a
[Markdown summary](results/2026-07-26-macos-arm64.md).

## Common workload

Each implementation registers the same 67 routes and response data:

| Scenario | Request | Response |
|---|---|---|
| Static text | `GET /text` | `hello` |
| Dynamic JSON | `GET /items/123` | `{"id":"123","name":"item-123"}` |
| 64-route dispatch | `GET /route63/value` | `ok` |
| JSON echo | `POST /echo` with `{"message":"hello"}` | `{"message":"hello","length":5}` |

The workload intentionally excludes databases, schema validation,
templates, and framework-specific middleware. It measures the framework
and transport path, not a complete production application.

## Metric definitions

- **App import**: fresh runtime process creation, framework import, and
  construction of all 67 routes. One discarded run warms filesystem caches;
  the reported value is the median of fresh processes.
- **Server ready**: fresh server process creation until its TCP listener
  accepts a connection.
- **Cold start**: fresh server process creation until the first successful
  `GET /text` response. It includes interpreter/runtime startup, imports,
  route construction, transport startup, and one request.
- **Production packages**: unique installed production distributions,
  including the framework and server adapter. Python uses Uvicorn + h11 for
  all three targets; Hono uses `@hono/node-server`. The Python and Node
  runtimes themselves are excluded.
- **gzip payload**: a deterministic gzip stream over the workload source and
  every file in the installed production package closure. It is a
  runtime-excluded deployment payload, not a container image size.
- **Throughput**: median requests/second from pinned autocannon runs over
  loopback, one HTTP/1.1 request in flight per connection. The summary is the
  geometric mean of all four scenarios. Framework order and scenario order
  rotate between rounds.
- **HTTP contract**: 14 black-box assertions covering exact workload
  responses plus RFC 9110 method and HEAD behavior. This is not a universal
  Web-standards score. hayate's URL and URLPattern WPT results stay separate
  in [the conformance report](../../docs/conformance.md).

Raw reports include every sample, resolved transitive package version,
benchmark configuration, Git commit, operating system, CPU, architecture,
and tool version.

## Fairness and interpretation

- Python targets use exactly the same Uvicorn 0.51.0 configuration:
  one process, asyncio, h11, lifespan disabled, and access logs disabled.
- Hono uses its documented Node adapter because it is not an ASGI
  framework. Runtime startup is part of cold start, while the runtime binary
  is excluded from deployment payload for all targets.
- The workload uses each framework's normal response and routing APIs.
  FastAPI's OpenAPI endpoints are disabled because the common workload does
  not expose an API schema endpoint.
- Shared CI hosts are noisy. Scheduled results are evidence with complete
  machine metadata, not a hard performance gate. Compare commits on the same
  dedicated host before treating a small difference as a regression.
- Results describe these versions, configuration, workload, and machine.
  They do not prove that one framework is universally faster.

## Updating pins

Dependency changes are deliberate review events. Edit the exact direct
version, regenerate only its lock, inspect the diff, and rerun the full suite:

```sh
uv lock --project benchmarks/competitive/apps/hayate
uv lock --project benchmarks/competitive/apps/fastapi
uv lock --project benchmarks/competitive/apps/django
npm install --package-lock-only --ignore-scripts \
  --prefix benchmarks/competitive/apps/hono
npm install --package-lock-only --ignore-scripts \
  --prefix benchmarks/competitive/load
```

The [monthly GitHub Actions workflow](../../.github/workflows/competitive-benchmark.yml)
also supports a manual run and uploads both raw JSON and Markdown artifacts.
