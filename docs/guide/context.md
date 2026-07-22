# Context and responses

Handlers receive a single `Context` (`c`), Hono-style. `c.req` wraps the
standard Fetch `Request` (raw object at `c.req.raw`) and adds routing
context; helpers build standard `Response` objects.

## Reading the request

```python
@app.post("/upload")
async def upload(c):
    c.req.method                 # "POST"
    c.req.url.pathname           # WHATWG URL
    c.req.header("content-type") # combined per Fetch
    c.req.cookies                # dict, RFC 6265bis parsing

    data = await c.req.json()    # or .text() / .bytes() / .form_data()
```

Bodies are one-shot per the Fetch Standard (`body_used`); `c.req.raw.clone()`
tees the stream when you need to read twice.

## Building responses

```python
return c.json({"ok": True})                  # application/json
return c.text("hello")                       # text/plain;charset=utf-8
return c.html("<h1>hi</h1>")                 # text/html
return c.body(raw_bytes, 200, headers={...}) # anything
return c.redirect("/next", 303)
return Response(None, 204)                   # raw Response always works
```

Streaming is just an async iterable of bytes:

```python
async def numbers():
    for i in range(5):
        yield f"{i}\n".encode()

return c.body(numbers())
```

## Errors: RFC 9457 everywhere

```python
raise HTTPException(422, title="Unprocessable", detail="year must be > 0",
                    extensions={"field": "year"})
```

produces `application/problem+json`. Framework-generated 404/405/500 use the
same format. Override with `@app.on_error` / `@app.not_found`.

## Cross-cutting state and headers

```python
@app.use
async def auth(c, next_):
    c.set("user", await lookup_user(c))   # typed hand-off to handlers
    await next_()
    c.header("x-served-by", "hayate")     # merged into the final response

@app.get("/me")
async def me(c):
    return c.json({"user": c.get("user")})
```

## After the response: `c.wait_until`

```python
@app.post("/orders")
async def order(c):
    c.wait_until(send_confirmation_email())   # runs after delivery
    return c.json({"ok": True}, 201)
```

Semantics match the Workers `ctx.waitUntil`: on ASGI the work is awaited
after the response is sent; on Cloudflare Workers it forwards to the
platform's own `waitUntil`.

## Cookies

```python
c.set_cookie("sid", token, http_only=True, secure=True, same_site="lax")
```

`__Host-`/`__Secure-` prefix invariants and `SameSite=None`-requires-`Secure`
are enforced at serialization time. HMAC signing helpers live in
`hayate.cookies` (`sign_value` / `unsign_value`).
