"""v0.2 middleware: body_limit, timeout, secure_headers."""

import asyncio

from hayate import Context, Hayate, Request
from hayate.middleware import body_limit, secure_headers, timeout

# -- body_limit ---------------------------------------------------------------


def _upload_app(max_size: int) -> Hayate:
    app = Hayate()
    app.use(body_limit(max_size=max_size))

    @app.post("/upload")
    async def upload(c: Context):
        data = await c.req.bytes()
        return c.text(str(len(data)))

    return app


async def test_body_limit_rejects_declared_size():
    app = _upload_app(10)
    res = await app.request(
        "/upload", method="POST", body="x" * 11, headers={"content-length": "11"}
    )
    assert res.status == 413


async def test_body_limit_rejects_buffered_body():
    app = _upload_app(10)
    res = await app.request("/upload", method="POST", body="x" * 11)
    assert res.status == 413


async def test_body_limit_rejects_streams_while_reading():
    app = _upload_app(10)

    async def chunks():
        yield b"x" * 8
        yield b"y" * 8

    res = await app.fetch(Request("http://localhost/upload", method="POST", body=chunks()))
    assert res.status == 413


async def test_body_limit_allows_small_bodies():
    app = _upload_app(10)
    res = await app.request("/upload", method="POST", body="tiny")
    assert res.status == 200
    assert await res.text() == "4"


# -- timeout ------------------------------------------------------------------


async def test_timeout_returns_504():
    app = Hayate()
    app.use(timeout(seconds=0.01))

    @app.get("/slow")
    async def slow(c: Context):
        await asyncio.sleep(0.5)
        return c.text("late")

    res = await app.request("/slow")
    assert res.status == 504


async def test_timeout_passes_fast_handlers():
    app = Hayate()
    app.use(timeout(seconds=1.0))

    @app.get("/fast")
    async def fast(c: Context):
        return c.text("ok")

    res = await app.request("/fast")
    assert res.status == 200


# -- secure_headers ------------------------------------------------------------


async def test_secure_headers_defaults():
    app = Hayate()
    app.use(secure_headers())

    @app.get("/")
    async def root(c: Context):
        return c.text("ok")

    res = await app.request("/")
    assert res.headers.get("x-content-type-options") == "nosniff"
    assert res.headers.get("x-frame-options") == "SAMEORIGIN"
    assert res.headers.get("referrer-policy") == "no-referrer"
    assert res.headers.get("strict-transport-security") is not None


async def test_secure_headers_never_override():
    app = Hayate()
    app.use(secure_headers())

    @app.get("/")
    async def root(c: Context):
        return c.text("ok", headers={"x-frame-options": "DENY"})

    res = await app.request("/")
    assert res.headers.get("x-frame-options") == "DENY"


async def test_secure_headers_disable_one():
    app = Hayate()
    app.use(secure_headers(strict_transport_security=None))

    @app.get("/")
    async def root(c: Context):
        return c.text("ok")

    res = await app.request("/")
    assert res.headers.get("strict-transport-security") is None
    assert res.headers.get("x-content-type-options") == "nosniff"
