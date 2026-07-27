"""Built-in middleware: cors, etag, basic_auth, compress, logger, request IDs."""

import asyncio
import base64
import gzip as gzip_module
import json
import logging
import re

import pytest

from hayate import Context, Hayate
from hayate.middleware import (
    RequestIdFilter,
    basic_auth,
    compress,
    cors,
    current_request_id,
    etag,
    logger,
    request_id,
)


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


async def test_cors_context_resolver_reads_runtime_env_for_simple_and_preflight():
    app = Hayate(env={"CORS_ORIGINS": {"https://folio.example"}})

    def from_env(c: Context, request_origin: str) -> str | None:
        return request_origin if request_origin in c.env["CORS_ORIGINS"] else None

    app.use(cors(origin_resolver=from_env))

    @app.get("/data")
    async def data(c: Context):
        return c.text("ok")

    allowed = await app.request("/data", headers={"origin": "https://folio.example"})
    assert allowed.headers.get("access-control-allow-origin") == "https://folio.example"

    denied = await app.request("/data", headers={"origin": "https://evil.example"})
    assert denied.headers.get("access-control-allow-origin") is None

    preflight = await app.request(
        "/data",
        method="OPTIONS",
        headers={
            "origin": "https://folio.example",
            "access-control-request-method": "GET",
        },
    )
    assert preflight.status == 204
    assert preflight.headers.get("access-control-allow-origin") == "https://folio.example"


async def test_cors_context_resolver_may_be_async():
    async def resolve(c: Context, request_origin: str) -> str | None:
        return request_origin if c.env else None

    app = Hayate(env=True)
    app.use(cors(origin_resolver=resolve))

    @app.get("/")
    async def home(c: Context):
        return c.text("ok")

    res = await app.request("/", headers={"origin": "https://folio.example"})
    assert res.headers.get("access-control-allow-origin") == "https://folio.example"


def test_cors_rejects_two_origin_configuration_sources():
    with pytest.raises(ValueError):
        cors(origin="https://fixed.example", origin_resolver=lambda c, origin: origin)


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


async def test_structured_logger_emits_safe_correlated_json(
    caplog: pytest.LogCaptureFixture,
):
    app = Hayate()
    app.use(request_id())
    app.use(logger(structured=True))

    @app.get("/items")
    async def items(c: Context):
        return c.text("ok")

    with caplog.at_level(logging.INFO, logger="hayate.request"):
        response = await app.request(
            "/items?token=must-not-be-logged",
            headers={"x-request-id": "folio:request-42"},
        )

    record = next(record for record in caplog.records if record.name == "hayate.request")
    payload = json.loads(record.getMessage())
    duration_ms = payload.pop("duration_ms")
    assert payload == {
        "event": "http_request",
        "method": "GET",
        "path": "/items",
        "status": 200,
        "request_id": "folio:request-42",
    }
    assert isinstance(duration_ms, float)
    assert duration_ms >= 0
    assert "must-not-be-logged" not in record.getMessage()
    assert record.__dict__["request_id"] == "folio:request-42"
    assert response.headers.get("x-request-id") == "folio:request-42"


async def test_structured_logger_covers_not_found_and_handled_errors(
    caplog: pytest.LogCaptureFixture,
):
    app = Hayate()
    app.use(request_id())
    app.use(logger(structured=True))

    @app.get("/error")
    async def fail(c: Context):
        raise RuntimeError("boom")

    with caplog.at_level(logging.INFO, logger="hayate.request"):
        missing = await app.request(
            "/missing",
            headers={"x-request-id": "missing-request"},
        )
        failed = await app.request(
            "/error",
            headers={"x-request-id": "failed-request"},
        )

    payloads = [
        json.loads(record.getMessage())
        for record in caplog.records
        if record.name == "hayate.request"
    ]
    assert [
        (payload["path"], payload["status"], payload["request_id"]) for payload in payloads
    ] == [
        ("/missing", 404, "missing-request"),
        ("/error", 500, "failed-request"),
    ]
    assert missing.headers.get("x-request-id") == "missing-request"
    assert failed.headers.get("x-request-id") == "failed-request"


# -- request ID ----------------------------------------------------------------------


async def test_request_id_generates_context_and_response_value():
    app = Hayate()
    app.use(request_id())
    seen: list[str] = []

    @app.get("/")
    async def root(c: Context):
        seen.append(c.get("request_id"))
        return c.text("ok")

    res = await app.request("/")
    value = res.headers.get("x-request-id")
    assert value is not None
    assert re.fullmatch(r"[0-9a-f]{32}", value)
    assert seen == [value]


async def test_request_id_preserves_safe_incoming_value():
    app = Hayate()
    app.use(request_id())

    @app.get("/")
    async def root(c: Context):
        return c.text(c.get("request_id"))

    res = await app.request("/", headers={"x-request-id": "edge:abc-123_4.5"})
    assert await res.text() == "edge:abc-123_4.5"
    assert res.headers.get("x-request-id") == "edge:abc-123_4.5"


@pytest.mark.parametrize("incoming", ["contains space", "café", "x" * 129])
async def test_request_id_replaces_unsafe_or_oversized_incoming_value(incoming: str):
    app = Hayate()
    app.use(request_id(generator=lambda _c: "safe-generated"))

    @app.get("/")
    async def root(c: Context):
        return c.text(c.get("request_id"))

    res = await app.request("/", headers={"x-request-id": incoming})
    assert await res.text() == "safe-generated"
    assert res.headers.get("x-request-id") == "safe-generated"


async def test_request_id_can_ignore_incoming_and_use_platform_generator():
    app = Hayate(env={"platform_request_id": "cf-ray-123"})
    app.use(
        request_id(
            accept_incoming=False,
            generator=lambda c: c.env["platform_request_id"],
        )
    )

    @app.get("/")
    async def root(c: Context):
        return c.text(c.get("request_id"))

    res = await app.request("/", headers={"x-request-id": "caller-value"})
    assert await res.text() == "cf-ray-123"
    assert res.headers.get("x-request-id") == "cf-ray-123"


async def test_request_id_covers_not_found_and_handled_errors():
    app = Hayate()
    app.use(request_id(generator=lambda _c: "correlated"))

    @app.get("/error")
    async def fail(c: Context):
        raise RuntimeError("boom")

    missing = await app.request("/missing")
    failed = await app.request("/error")
    assert missing.status == 404
    assert failed.status == 500
    assert missing.headers.get("x-request-id") == "correlated"
    assert failed.headers.get("x-request-id") == "correlated"


def test_request_id_rejects_invalid_configuration():
    with pytest.raises(ValueError, match="max_length"):
        request_id(max_length=0)


async def test_request_id_fails_closed_for_invalid_generator_value():
    app = Hayate()
    app.use(request_id(generator=lambda _c: "unsafe generated value"))

    @app.get("/")
    async def root(c: Context):
        return c.text("unreachable")

    res = await app.request("/")
    assert res.status == 500
    assert res.headers.get("x-request-id") is None


async def test_request_id_logging_context_is_concurrent_deferred_and_restored(
    caplog: pytest.LogCaptureFixture,
):
    assert current_request_id() is None
    application_log = logging.getLogger("hayate.test.request_context")
    correlation_filter = RequestIdFilter()
    application_log.addFilter(correlation_filter)

    app = Hayate()
    app.use(request_id())
    arrivals: list[str] = []
    both_arrived = asyncio.Event()

    async def deferred(name: str) -> None:
        await asyncio.sleep(0)
        application_log.info("background:%s", name)

    @app.get("/requests/:name")
    async def correlated(c: Context):
        name = c.req.param("name")
        expected = c.req.header("x-request-id")
        assert current_request_id() == expected
        arrivals.append(name)
        if len(arrivals) == 2:
            both_arrived.set()
        await both_arrived.wait()
        application_log.info("handler:%s", name)
        c.wait_until(deferred(name))
        return c.text(name)

    try:
        with caplog.at_level(logging.INFO, logger=application_log.name):
            left, right = await asyncio.gather(
                app.request(
                    "/requests/left",
                    headers={"x-request-id": "left-request"},
                ),
                app.request(
                    "/requests/right",
                    headers={"x-request-id": "right-request"},
                ),
            )
    finally:
        application_log.removeFilter(correlation_filter)

    assert left.headers.get("x-request-id") == "left-request"
    assert right.headers.get("x-request-id") == "right-request"
    assert current_request_id() is None
    correlated_records = {
        record.getMessage(): record.__dict__["request_id"]
        for record in caplog.records
        if record.name == application_log.name
    }
    assert correlated_records == {
        "handler:left": "left-request",
        "handler:right": "right-request",
        "background:left": "left-request",
        "background:right": "right-request",
    }
