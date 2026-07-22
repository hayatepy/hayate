# Routing

Route syntax is the [WHATWG URLPattern standard](https://urlpattern.spec.whatwg.org/)
— the same patterns that work in `new URLPattern()` in browsers, Node, Deno,
Bun, and Cloudflare Workers. hayate does not invent a routing DSL.

```python
@app.get("/books/:id")            # named parameter
@app.get(r"/books/:id(\d+)")      # with a regexp constraint
@app.get("/files/*")              # wildcard -> c.req.param("0")
@app.get("/posts/:slug?")         # optional (also matches /posts)
@app.on("PURGE", "/cache/:key")   # any method
```

Parameters are percent-decoded:

```python
@app.get("/items/:name")
async def item(c):
    c.req.param("name")   # "あ" for /items/%E3%81%82
    c.req.params          # all parameters as a dict
```

Query strings ride on the WHATWG `URLSearchParams` model:

```python
@app.get("/search")
async def search(c):
    c.req.query("q")       # first value or None
    c.req.queries("tag")   # all values
    c.req.url.search_params  # the full URLSearchParams
```

## Matching rules

- Static paths always win over dynamic patterns, regardless of registration
  order; dynamic patterns match in registration order.
- A path that matches another method's route answers **405 with `Allow`**;
  no route at all answers 404 (both as RFC 9457 problem documents).
- `HEAD` falls back to the `GET` handler; the adapter strips the body and
  keeps `Content-Length`.

## The documented subset

The v0 series implements the URLPattern pathname component with `:name`,
`:name(regexp)`, anonymous `(regexp)` groups, the `?` modifier, and `*`
wildcards. `{}` groups and `+`/`*` modifiers are **rejected loudly at
registration time** (`ValueError`), never silently misrouted. Regexp groups
are interpreted by Python's `re`. Conformance against the wpt vectors is
measured on every test run — see [Conformance](../conformance.md).
