"""static_files (RFC 9110 §13/§14) and the response micro-cache."""

from hayate import Context, Hayate
from hayate.middleware import cache, static_files

# -- static_files -------------------------------------------------------------


def _static_app(tmp_path) -> Hayate:
    site = tmp_path / "site"
    site.mkdir()
    (site / "hello.txt").write_text("hello static")
    (site / "index.html").write_text("<h1>home</h1>")
    app = Hayate()
    app.use("/assets/*", static_files(root=site, strip_prefix="/assets"))
    return app


async def test_serves_file_with_metadata(tmp_path):
    app = _static_app(tmp_path)
    res = await app.request("/assets/hello.txt")
    assert res.status == 200
    assert await res.text() == "hello static"
    assert res.headers.get("content-type") == "text/plain"
    assert res.headers.get("accept-ranges") == "bytes"
    assert (res.headers.get("etag") or "").startswith('W/"')


async def test_conditional_304(tmp_path):
    app = _static_app(tmp_path)
    first = await app.request("/assets/hello.txt")
    tag = first.headers.get("etag")
    assert tag is not None
    second = await app.request("/assets/hello.txt", headers={"if-none-match": tag})
    assert second.status == 304
    assert second.body is None


async def test_single_range(tmp_path):
    app = _static_app(tmp_path)
    res = await app.request("/assets/hello.txt", headers={"range": "bytes=0-4"})
    assert res.status == 206
    assert await res.text() == "hello"
    assert res.headers.get("content-range") == "bytes 0-4/12"


async def test_suffix_range(tmp_path):
    app = _static_app(tmp_path)
    res = await app.request("/assets/hello.txt", headers={"range": "bytes=-6"})
    assert res.status == 206
    assert await res.text() == "static"
    assert res.headers.get("content-range") == "bytes 6-11/12"


async def test_unsatisfiable_range_is_416(tmp_path):
    app = _static_app(tmp_path)
    res = await app.request("/assets/hello.txt", headers={"range": "bytes=100-"})
    assert res.status == 416
    assert res.headers.get("content-range") == "bytes */12"


async def test_multiple_ranges_ignored(tmp_path):
    app = _static_app(tmp_path)
    res = await app.request("/assets/hello.txt", headers={"range": "bytes=0-1,4-5"})
    assert res.status == 200
    assert await res.text() == "hello static"


async def test_directory_serves_index(tmp_path):
    app = _static_app(tmp_path)
    res = await app.request("/assets/")
    assert res.status == 200
    assert "home" in await res.text()


async def test_missing_file_falls_through_to_404(tmp_path):
    app = _static_app(tmp_path)
    res = await app.request("/assets/nope.txt")
    assert res.status == 404


async def test_path_traversal_blocked(tmp_path):
    (tmp_path / "secret.txt").write_text("top secret")
    app = _static_app(tmp_path)
    res = await app.request("/assets/%2e%2e/secret.txt")
    assert res.status == 404


async def test_non_get_falls_through(tmp_path):
    app = _static_app(tmp_path)
    res = await app.request("/assets/hello.txt", method="POST")
    assert res.status in (404, 405)


# -- cache --------------------------------------------------------------------


async def test_cache_serves_hit_without_rerunning_handler():
    app = Hayate()
    app.use(cache(max_age=60))
    calls: list[int] = []

    @app.get("/data")
    async def data(c: Context):
        calls.append(1)
        return c.json({"n": len(calls)})

    first = await app.request("/data")
    assert await first.json() == {"n": 1}
    assert first.headers.get("cache-control") == "public, max-age=60"

    second = await app.request("/data")
    assert await second.json() == {"n": 1}
    assert second.headers.get("age") is not None
    assert calls == [1]


async def test_cache_key_includes_query():
    app = Hayate()
    app.use(cache(max_age=60))

    @app.get("/q")
    async def q(c: Context):
        return c.json({"v": c.req.query("v")})

    assert await (await app.request("/q?v=1")).json() == {"v": "1"}
    assert await (await app.request("/q?v=2")).json() == {"v": "2"}


async def test_cache_skips_errors_and_non_get():
    app = Hayate()
    app.use(cache(max_age=60))
    calls: list[int] = []

    @app.post("/w")
    async def w(c: Context):
        calls.append(1)
        return c.json({"n": len(calls)})

    await app.request("/w", method="POST")
    await app.request("/w", method="POST")
    assert calls == [1, 1]

    missing = await app.request("/nope")
    assert missing.status == 404
    assert missing.headers.get("cache-control") is None


async def test_cache_private_directive():
    app = Hayate()
    app.use(cache(max_age=5, private=True))

    @app.get("/me")
    async def me(c: Context):
        return c.text("mine")

    res = await app.request("/me")
    assert res.headers.get("cache-control") == "private, max-age=5"
