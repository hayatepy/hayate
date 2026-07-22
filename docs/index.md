# hayate

**Web-standards-first Python web framework, inspired by [Hono](https://hono.dev).**

hayate (疾風, *swift wind*) brings the Fetch API model to Python. Everything you
touch maps 1:1 to WHATWG / IETF web standards; Python-local protocols such as
WSGI and ASGI are demoted to adapter-level details.

```python
from hayate import Hayate, HTTPException

app = Hayate()

@app.get("/books/:id")
async def show_book(c):
    book = BOOKS.get(c.req.param("id"))
    if book is None:
        raise HTTPException(404, title="Book not found")
    return c.json(book)
```

## Why hayate

- **Standards-first** — `Request` / `Response` / `Headers` / `URL` follow WHATWG
  Fetch and URL semantics. Routing syntax is the WHATWG URLPattern standard
  (`/books/:id`), not a custom DSL. Errors are RFC 9457 `application/problem+json`.
  Learn MDN, and you know hayate.
- **Zero dependencies** — the core is standard library only. It runs anywhere
  CPython runs, including Pyodide (try it in the [playground](playground.md) —
  the framework runs in your browser).
- **One app, three runtimes** — the core is a pure `fetch(Request) -> Response`
  function. ASGI servers, Cloudflare Python Workers, and AWS Lambda are thin
  adapters. See [Runtimes](guide/runtimes.md).
- **Measured, not claimed** — standards conformance runs against vendored
  [web-platform-tests](https://github.com/web-platform-tests/wpt) with ratcheted
  pass counts ([Conformance](conformance.md)); framework overhead is benchmarked
  at or below Starlette's ([Benchmarks](benchmarks.md)).
- **Serverless testing** — `await app.request("/path")` calls the app directly.
  No server, no test client, milliseconds per test. See [Testing](guide/testing.md).

## Install

```sh
uv add hayate        # or: pip install hayate
```

Requires Python 3.12+. Optional native accelerator: `pip install hayate-accel`.

## Run it

```sh
uvicorn main:app
```

Any ASGI server works (uvicorn, hypercorn, granian). The same `app` deploys to
Cloudflare Workers with `to_workers(app)` and to AWS Lambda with
`to_lambda(app)` — see [Runtimes](guide/runtimes.md).

## Where next

- [Getting started](guide/getting-started.md) — a TODO API in 5 minutes
- [Playground](playground.md) — run hayate in your browser, right now
- [API reference](api.md)
