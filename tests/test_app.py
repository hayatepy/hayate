"""Hayate app: routing, middleware composition, errors, context."""

import asyncio

import pytest

from hayate import Context, Hayate, HTTPException


async def test_basic_get():
    app = Hayate()

    @app.get("/hello")
    async def hello(c: Context):
        return c.text("world")

    res = await app.request("/hello")
    assert res.status == 200
    assert await res.text() == "world"


async def test_path_params_are_percent_decoded():
    app = Hayate()

    @app.get("/items/:name")
    async def item(c: Context):
        return c.json({"name": c.req.param("name")})

    res = await app.request("/items/%E3%81%82")
    assert (await res.json())["name"] == "あ"


async def test_query_helpers():
    app = Hayate()

    @app.get("/q")
    async def q(c: Context):
        return c.json({"v": c.req.query("v"), "all": c.req.queries("v")})

    res = await app.request("/q?v=1&v=2")
    assert await res.json() == {"v": "1", "all": ["1", "2"]}


async def test_json_body_roundtrip():
    app = Hayate()

    @app.post("/echo")
    async def echo(c: Context):
        return c.json(await c.req.json())

    res = await app.request("/echo", method="POST", json={"x": [1, 2]})
    assert await res.json() == {"x": [1, 2]}


async def test_404_is_problem_json():
    app = Hayate()
    res = await app.request("/missing")
    assert res.status == 404
    assert res.headers.get("content-type") == "application/problem+json"
    body = await res.json()
    assert body["status"] == 404
    assert body["title"] == "Not Found"


async def test_405_includes_allow():
    app = Hayate()

    @app.get("/only-get")
    async def only_get(c: Context):
        return c.text("ok")

    res = await app.request("/only-get", method="POST")
    assert res.status == 405
    assert res.headers.get("allow") == "GET, HEAD"


async def test_head_falls_back_to_get():
    app = Hayate()

    @app.get("/page")
    async def page(c: Context):
        return c.text("content")

    res = await app.request("/page", method="HEAD")
    assert res.status == 200
    # Body suppression for HEAD is transport-level (adapter) behavior.


async def test_middleware_onion_order():
    app = Hayate()
    order: list[str] = []

    @app.use
    async def outer(c: Context, next_):
        order.append("outer-in")
        await next_()
        order.append("outer-out")

    @app.use
    async def inner(c: Context, next_):
        order.append("inner-in")
        await next_()
        order.append("inner-out")

    @app.get("/")
    async def root(c: Context):
        order.append("handler")
        return c.text("x")

    await app.request("/")
    assert order == ["outer-in", "inner-in", "handler", "inner-out", "outer-out"]


async def test_scoped_middleware_only_matches_pattern():
    app = Hayate()

    @app.use("/admin/*")
    async def guard(c: Context, next_):
        c.set("admin", True)
        await next_()

    @app.get("/admin/panel")
    async def panel(c: Context):
        return c.json({"admin": c.get("admin")})

    @app.get("/public")
    async def public(c: Context):
        return c.json({"admin": c.get("admin")})

    assert (await (await app.request("/admin/panel")).json())["admin"] is True
    assert (await (await app.request("/public")).json())["admin"] is None


async def test_route_level_middleware():
    app = Hayate()

    async def tag(c: Context, next_):
        c.set("tag", "yes")
        await next_()

    @app.get("/tagged", tag)
    async def tagged(c: Context):
        return c.json({"tag": c.get("tag")})

    assert (await (await app.request("/tagged")).json())["tag"] == "yes"


async def test_c_header_merged_into_final_response():
    app = Hayate()

    @app.use
    async def timing(c: Context, next_):
        await next_()
        c.header("x-timing", "1ms")

    @app.get("/")
    async def root(c: Context):
        return c.text("ok")

    res = await app.request("/")
    assert res.headers.get("x-timing") == "1ms"


async def test_http_exception_becomes_problem_json():
    app = Hayate()

    @app.get("/teapot")
    async def teapot(c: Context):
        raise HTTPException(
            418, title="I'm a teapot", detail="short and stout", extensions={"pot": True}
        )

    res = await app.request("/teapot")
    assert res.status == 418
    body = await res.json()
    assert body["title"] == "I'm a teapot"
    assert body["detail"] == "short and stout"
    assert body["pot"] is True


async def test_unhandled_error_does_not_leak_detail():
    app = Hayate()

    @app.get("/boom")
    async def boom(c: Context):
        raise RuntimeError("secret database password")

    res = await app.request("/boom")
    assert res.status == 500
    body = await res.json()
    assert "secret" not in (body.get("detail") or "")


async def test_debug_mode_includes_traceback():
    app = Hayate(debug=True)

    @app.get("/boom")
    async def boom(c: Context):
        raise RuntimeError("kaboom")

    body = await (await app.request("/boom")).json()
    assert "RuntimeError" in body["detail"]
    assert "kaboom" in body["detail"]


async def test_on_error_hook_overrides_default():
    app = Hayate()

    @app.get("/x")
    async def x(c: Context):
        raise ValueError("nope")

    @app.on_error
    async def handle(err: Exception, c: Context):
        return c.json({"custom": str(err)}, 502)

    res = await app.request("/x")
    assert res.status == 502
    assert (await res.json())["custom"] == "nope"


async def test_custom_not_found():
    app = Hayate()

    @app.not_found
    async def nf(c: Context):
        return c.text("gone", 404)

    res = await app.request("/none")
    assert res.status == 404
    assert await res.text() == "gone"


async def test_middleware_runs_even_without_route():
    app = Hayate()
    hits: list[int] = []

    @app.use
    async def mw(c: Context, next_):
        hits.append(1)
        await next_()

    res = await app.request("/nope")
    assert res.status == 404
    assert hits == [1]


async def test_sync_handler_runs_in_thread():
    app = Hayate()

    @app.get("/sync")
    def sync_handler(c: Context):
        return c.text("from-thread")

    res = await app.request("/sync")
    assert await res.text() == "from-thread"


async def test_wait_until_completes_before_request_returns():
    app = Hayate()
    done = asyncio.Event()

    async def background():
        done.set()

    @app.get("/")
    async def root(c: Context):
        c.wait_until(background())
        return c.text("ok")

    await app.request("/")
    assert done.is_set()


async def test_middleware_may_return_response_to_short_circuit():
    app = Hayate()

    @app.use
    async def short_circuit(c: Context, next_):
        return c.text("intercepted", 403)

    @app.get("/")
    async def root(c: Context):
        return c.text("never")

    res = await app.request("/")
    assert res.status == 403
    assert await res.text() == "intercepted"


def test_sync_middleware_rejected():
    app = Hayate()
    with pytest.raises(TypeError):
        app.use(lambda c, n: None)  # type: ignore[arg-type]


def test_duplicate_route_rejected():
    app = Hayate()

    @app.get("/a")
    async def a(c: Context):
        return c.text("1")

    with pytest.raises(ValueError):

        @app.get("/a")
        async def b(c: Context):
            return c.text("2")


async def test_env_is_available_on_context():
    app = Hayate(env={"DB": "conn"})

    @app.get("/")
    async def root(c: Context):
        return c.json({"db": c.env["DB"]})

    assert (await (await app.request("/")).json())["db"] == "conn"


async def test_wildcard_param_available():
    app = Hayate()

    @app.get("/files/*")
    async def files(c: Context):
        return c.json({"path": c.req.param("0")})

    res = await app.request("/files/a/b.txt")
    assert (await res.json())["path"] == "a/b.txt"


async def test_next_called_twice_is_an_error():
    app = Hayate()

    @app.use
    async def bad(c: Context, next_):
        await next_()
        await next_()

    @app.get("/")
    async def root(c: Context):
        return c.text("ok")

    res = await app.request("/")
    assert res.status == 500
