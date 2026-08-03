"""static_files (RFC 9110 §13/§14) and the response micro-cache."""

import pytest

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
    app.use(cache(max_age=5, private=True, key=lambda c: c.req.header("x-user")))
    calls: list[str] = []

    @app.get("/me")
    async def me(c: Context):
        user = c.req.header("x-user") or "anonymous"
        calls.append(user)
        return c.text(user)

    alice = await app.request("/me", headers={"x-user": "alice"})
    bob = await app.request("/me", headers={"x-user": "bob"})
    alice_again = await app.request("/me", headers={"x-user": "alice"})
    assert alice.headers.get("cache-control") == "private, max-age=5"
    assert await bob.text() == "bob"
    assert await alice_again.text() == "alice"
    assert calls == ["alice", "bob"]


def test_private_cache_requires_identity_key():
    with pytest.raises(ValueError, match="identity key"):
        cache(max_age=5, private=True)


@pytest.mark.parametrize("header_name", ["authorization", "proxy-authorization", "cookie"])
async def test_cache_bypasses_credentials_without_identity_key(header_name: str):
    app = Hayate()
    app.use(cache(max_age=60))
    calls: list[str] = []

    @app.get("/credential")
    async def credential(c: Context):
        value = c.req.header(header_name) or "missing"
        calls.append(value)
        return c.text(value)

    first = await app.request("/credential", headers={header_name: "alice"})
    second = await app.request("/credential", headers={header_name: "bob"})
    assert first.headers.get("cache-control") is None
    assert await second.text() == "bob"
    assert calls == ["alice", "bob"]


async def test_cache_does_not_store_set_cookie_response():
    app = Hayate()
    app.use(cache(max_age=60, key=lambda c: "partition"))
    calls: list[int] = []

    @app.get("/session")
    async def session(c: Context):
        calls.append(1)
        return c.text(str(len(calls)), headers={"set-cookie": "session=secret"})

    assert await (await app.request("/session")).text() == "1"
    assert await (await app.request("/session")).text() == "2"
    assert calls == [1, 1]


async def test_cache_total_bytes_bound_skips_oversized_entry():
    app = Hayate()
    app.use(cache(max_age=60, max_bytes=1))
    calls: list[int] = []

    @app.get("/large")
    async def large(c: Context):
        calls.append(1)
        return c.text("larger than one byte")

    first = await app.request("/large")
    second = await app.request("/large")
    assert first.headers.get("cache-control") == "public, max-age=60"
    assert await second.text() == "larger than one byte"
    assert calls == [1, 1]


async def test_cache_total_bytes_bound_evicts_least_recently_used_entry():
    app = Hayate()
    app.use(cache(max_age=60, max_bytes=100))
    calls: list[str] = []

    @app.get("/:name")
    async def item(c: Context):
        name = c.req.param("name")
        calls.append(name)
        return c.text(name)

    assert await (await app.request("/a")).text() == "a"
    assert await (await app.request("/b")).text() == "b"
    assert await (await app.request("/b")).text() == "b"
    assert await (await app.request("/a")).text() == "a"
    assert calls == ["a", "b", "a"]


async def test_explicit_cache_key_implies_private_response():
    app = Hayate()
    app.use(cache(max_age=60, key=lambda c: "partition"))

    @app.get("/keyed")
    async def keyed(c: Context):
        return c.text("keyed")

    response = await app.request("/keyed")
    assert response.headers.get("cache-control") == "private, max-age=60"


def test_cache_limits_are_validated():
    with pytest.raises(ValueError, match="max_age"):
        cache(max_age=-1)
    with pytest.raises(ValueError, match="max_entries"):
        cache(max_age=1, max_entries=0)
    with pytest.raises(ValueError, match="max_bytes"):
        cache(max_age=1, max_bytes=0)
