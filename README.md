# hayate

> A web-standards-first Python web framework, inspired by [Hono](https://hono.dev).

**hayate** (疾風, "swift wind") brings the Fetch API model to Python. Everything you touch
maps 1:1 to WHATWG / IETF web standards; Python-local protocols such as WSGI and ASGI are
demoted to adapter-level implementation details.

- **Standards-first** — `Request` / `Response` / `Headers` / `URL` follow WHATWG Fetch and URL
  semantics. Routing syntax is the WHATWG URLPattern standard (`/books/:id`), not a custom DSL.
- **Zero dependencies** — standard library only. Runs anywhere CPython (or Pyodide) runs.
- **Runtime-agnostic** — the app core is a pure `fetch(Request) -> Response` function.
  ASGI servers, Cloudflare Python Workers, and AWS Lambda are thin adapters.
- **Async-first, typed** — Python 3.12+.

## Install

```sh
uv add hayate        # or: pip install hayate
```

## Quickstart

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

Run with any ASGI server:

```sh
uvicorn main:app
```

## Testing without a server

The app core performs no I/O, so tests call it directly — no test client, no sockets:

```python
async def test_show_book():
    res = await app.request("/books/1")
    assert res.status == 200
    assert (await res.json())["id"] == "1"
```

## Conformance and performance, measured

- Standards conformance runs against vendored [web-platform-tests](https://github.com/web-platform-tests/wpt)
  vectors on every `pytest` run, with ratcheted pass counts —
  see [docs/conformance.md](docs/conformance.md).
- Framework overhead is benchmarked against Starlette (1.2x on simple
  routes, 1.9x at 64 routes; optional Rust accelerator included) — see
  [docs/benchmarks.md](docs/benchmarks.md).

## Status

Alpha (0.3.x): the surface tracks [DESIGN.md](DESIGN.md) (Japanese) and may still move
before 1.0. Changes are recorded in [CHANGELOG.md](CHANGELOG.md); platform research
lives in [docs/research/](docs/research/).

## License

MIT
