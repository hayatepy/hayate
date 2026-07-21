"""Built-in middleware: cors, etag, basic_auth, compress, logger."""

import base64
import gzip as gzip_module
import logging

import pytest

from hayate import Context, Hayate
from hayate.middleware import basic_auth, compress, cors, etag, logger


def _basic(user: str, password: str) -> str:
    return "Basic " + base64.b64encode(f"{user}:{password}".encode()).decode()


# -- cors ---------------------------------------------------------------------


def _cors_app(**options) -> Hayate:
    app = Hayate()
    app.use(cors(**options))

    @app.get("/data")
    async def data(c: Context):
        return c.json({"ok": True})

    @app.post("/data")
    async def create(c: Context):
        return c.json({"ok": True}, 201)

    return app


async def test_cors_simple_request_wildcard():
    app = _cors_app()
    res = await app.request("/data", headers={"origin": "https://site.example"})
    assert res.headers.get("access-control-allow-origin") == "*"


async def test_cors_without_origin_header_is_untouched():
    app = _cors_app()
    res = await app.request("/data")
    assert res.headers.get("access-control-allow-origin") is None


async def test_cors_preflight():
    app = _cors_app(origin=["https://site.example"], max_age=600)
    res = await app.request(
        "/data",
        method="OPTIONS",
        headers={
            "origin": "https://site.example",
            "access-control-request-method": "POST",
            "access-control-request-headers": "content-type",
        },
    )
    assert res.status == 204
    assert res.headers.get("access-control-allow-origin") == "https://site.example"
    assert res.headers.get("access-control-allow-methods") == "GET, HEAD, PUT, POST, DELETE, PATCH"
    assert res.headers.get("access-control-allow-headers") == "content-type"
    assert res.headers.get("access-control-max-age") == "600"


async def test_cors_disallowed_origin_gets_no_headers():
    app = _cors_app(origin=["https://ok.example"])
    res = await app.request("/data", headers={"origin": "https://evil.example"})
    assert res.headers.get("access-control-allow-origin") is None


async def test_cors_credentials_echoes_origin_instead_of_wildcard():
    app = _cors_app(credentials=True)
    res = await app.request("/data", headers={"origin": "https://site.example"})
    assert res.headers.get("access-control-allow-origin") == "https://site.example"
    assert res.headers.get("access-control-allow-credentials") == "true"
    assert "origin" in (res.headers.get("vary") or "").lower()


# -- etag ---------------------------------------------------------------------


def _etag_app() -> Hayate:
    app = Hayate()
    app.use(etag())

    @app.get("/doc")
    async def doc(c: Context):
        return c.text("stable content")

    return app


async def test_etag_set_and_304_on_match():
    app = _etag_app()
    first = await app.request("/doc")
    tag = first.headers.get("etag")
    assert tag is not None and tag.startswith('W/"')
    second = await app.request("/doc", headers={"if-none-match": tag})
    assert second.status == 304
    assert second.headers.get("etag") == tag
    assert second.body is None


async def test_etag_mismatch_returns_full_response():
    app = _etag_app()
    res = await app.request("/doc", headers={"if-none-match": 'W/"different"'})
    assert res.status == 200
    assert await res.text() == "stable content"


async def test_etag_star_matches():
    app = _etag_app()
    res = await app.request("/doc", headers={"if-none-match": "*"})
    assert res.status == 304


# -- basic_auth -----------------------------------------------------------------


def _auth_app() -> Hayate:
    app = Hayate()
    app.use(basic_auth(username="admin", password="secret"))

    @app.get("/")
    async def root(c: Context):
        return c.text("in")

    return app


async def test_basic_auth_challenges_without_credentials():
    app = _auth_app()
    res = await app.request("/")
    assert res.status == 401
    challenge = res.headers.get("www-authenticate")
    assert challenge is not None and 'Basic realm="Restricted"' in challenge


async def test_basic_auth_accepts_valid_credentials():
    app = _auth_app()
    res = await app.request("/", headers={"authorization": _basic("admin", "secret")})
    assert res.status == 200
    assert await res.text() == "in"


async def test_basic_auth_rejects_wrong_password():
    app = _auth_app()
    res = await app.request("/", headers={"authorization": _basic("admin", "wrong")})
    assert res.status == 401


async def test_basic_auth_rejects_garbage_base64():
    app = _auth_app()
    res = await app.request("/", headers={"authorization": "Basic !!!not-base64!!!"})
    assert res.status == 401


# -- compress ----------------------------------------------------------------------


def _compress_app(payload: str, content_type: str | None = None, **options) -> Hayate:
    app = Hayate()
    app.use(compress(**options))

    @app.get("/big")
    async def big(c: Context):
        if content_type is not None:
            return c.body(payload.encode(), headers={"content-type": content_type})
        return c.text(payload)

    return app


async def test_compress_gzip():
    payload = "x" * 500
    app = _compress_app(payload, min_size=10)
    res = await app.request("/big", headers={"accept-encoding": "gzip"})
    assert res.headers.get("content-encoding") == "gzip"
    assert res.headers.get("vary") == "accept-encoding"
    assert isinstance(res.body, bytes)
    assert gzip_module.decompress(res.body).decode() == payload


async def test_compress_zstd_preferred_when_available():
    zstd = pytest.importorskip("compression.zstd", reason="zstd needs Python 3.14+")
    payload = "y" * 500
    app = _compress_app(payload, min_size=10)
    res = await app.request("/big", headers={"accept-encoding": "zstd, gzip"})
    assert res.headers.get("content-encoding") == "zstd"
    assert isinstance(res.body, bytes)
    assert zstd.decompress(res.body).decode() == payload


async def test_compress_skips_small_bodies():
    app = _compress_app("tiny")
    res = await app.request("/big", headers={"accept-encoding": "gzip"})
    assert res.headers.get("content-encoding") is None


async def test_compress_skips_non_compressible_types():
    app = _compress_app("z" * 5000, content_type="image/png", min_size=10)
    res = await app.request("/big", headers={"accept-encoding": "gzip"})
    assert res.headers.get("content-encoding") is None


async def test_compress_respects_q_zero():
    app = _compress_app("w" * 5000, min_size=10)
    res = await app.request("/big", headers={"accept-encoding": "gzip;q=0"})
    assert res.headers.get("content-encoding") is None


# -- logger --------------------------------------------------------------------------


async def test_logger_emits_line(caplog: pytest.LogCaptureFixture):
    app = Hayate()
    app.use(logger())

    @app.get("/")
    async def root(c: Context):
        return c.text("ok")

    with caplog.at_level(logging.INFO, logger="hayate.request"):
        await app.request("/")
    assert any("GET / -> 200" in record.getMessage() for record in caplog.records)
