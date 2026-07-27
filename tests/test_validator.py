"""The validator hook and schema-library integration."""

import pytest

from hayate import Context, FormDataLimitError, FormDataLimits, Hayate, Request
from hayate.validator import validator


def _require_title(data: dict) -> dict:
    title = data.get("title")
    if not isinstance(title, str) or not title.strip():
        raise ValueError("'title' must be a non-empty string")
    return {"title": title.strip()}


def make_app() -> Hayate:
    app = Hayate()

    @app.post("/books", validator("json", _require_title))
    async def create(c: Context):
        return c.json(c.req.valid("json"), 201)

    @app.get("/search", validator("query", _require_title))
    async def search(c: Context):
        return c.json(c.req.valid("query"))

    @app.post("/form", validator("form", _require_title))
    async def form(c: Context):
        return c.json(c.req.valid("form"))

    @app.get("/authors/:title", validator("param", _require_title))
    async def route_param(c: Context):
        return c.json(c.req.valid("param"))

    @app.get("/header", validator("header", _require_title))
    async def header(c: Context):
        return c.json(c.req.valid("header"))

    @app.get("/cookie", validator("cookie", _require_title))
    async def cookie(c: Context):
        return c.json(c.req.valid("cookie"))

    return app


async def test_json_validation_success():
    app = make_app()
    res = await app.request("/books", method="POST", json={"title": "  SICP "})
    assert res.status == 201
    assert await res.json() == {"title": "SICP"}


async def test_json_validation_failure_is_problem():
    app = make_app()
    res = await app.request("/books", method="POST", json={"title": ""})
    assert res.status == 400
    body = await res.json()
    assert body["title"] == "Validation failed"
    assert "'title'" in body["detail"]


async def test_malformed_json_body_is_400():
    app = make_app()
    res = await app.request(
        "/books", method="POST", body="not json", headers={"content-type": "application/json"}
    )
    assert res.status == 400
    assert (await res.json())["detail"] == "request body is not valid JSON"


async def test_query_validation():
    app = make_app()
    assert (await app.request("/search?title=hi")).status == 200
    assert (await app.request("/search")).status == 400


async def test_form_validation():
    app = make_app()
    res = await app.request(
        "/form",
        method="POST",
        body="title=hello",
        headers={"content-type": "application/x-www-form-urlencoded"},
    )
    assert res.status == 200
    assert await res.json() == {"title": "hello"}


async def test_form_parse_error_is_problem():
    app = make_app()
    res = await app.request(
        "/form",
        method="POST",
        body="ignored",
        headers={"content-type": "multipart/form-data"},
    )
    assert res.status == 400
    body = await res.json()
    assert body["title"] == "Validation failed"
    assert "boundary" in body["detail"]


async def test_form_limit_error_is_payload_too_large(monkeypatch):
    async def over_limit(
        self: Request,
        limits: FormDataLimits | None = None,
    ):
        raise FormDataLimitError("form body exceeds max_body_bytes")

    monkeypatch.setattr(Request, "form_data", over_limit)
    app = make_app()
    res = await app.request(
        "/form",
        method="POST",
        body="title=hello",
        headers={"content-type": "application/x-www-form-urlencoded"},
    )
    assert res.status == 413
    body = await res.json()
    assert body["title"] == "Payload Too Large"
    assert body["detail"] == "form body exceeds max_body_bytes"


async def test_route_parameter_validation_uses_decoded_values():
    app = make_app()
    res = await app.request("/authors/The%20Dispossessed")
    assert res.status == 200
    assert await res.json() == {"title": "The Dispossessed"}


async def test_header_validation_uses_lowercase_fetch_combined_values():
    app = make_app()
    res = await app.request(
        "/header",
        headers=[("TITLE", "The Left Hand"), ("Title", "of Darkness")],
    )
    assert res.status == 200
    assert await res.json() == {"title": "The Left Hand, of Darkness"}


async def test_cookie_validation_uses_parsed_cookie_pairs():
    app = make_app()
    res = await app.request("/cookie", headers={"cookie": "title=Kindred; theme=dark"})
    assert res.status == 200
    assert await res.json() == {"title": "Kindred"}


@pytest.mark.parametrize(
    ("path", "headers"),
    [
        ("/header", {}),
        ("/cookie", {}),
    ],
)
async def test_non_body_target_validation_failure_is_problem(path, headers):
    app = make_app()
    res = await app.request(path, headers=headers)
    assert res.status == 400
    assert (await res.json())["title"] == "Validation failed"


def test_unknown_target_rejected():
    with pytest.raises(ValueError):
        validator("body", _require_title)  # type: ignore[arg-type]


async def test_msgspec_integration():
    msgspec = pytest.importorskip("msgspec", reason="msgspec not installed")

    class BookIn(msgspec.Struct):
        title: str
        year: int

    app = Hayate()

    @app.post("/books", validator("json", lambda data: msgspec.convert(data, BookIn)))
    async def create(c: Context):
        book = c.req.valid("json")
        return c.json({"title": book.title, "year": book.year}, 201)

    ok = await app.request("/books", method="POST", json={"title": "SICP", "year": 1985})
    assert ok.status == 201
    assert await ok.json() == {"title": "SICP", "year": 1985}

    bad = await app.request("/books", method="POST", json={"title": "SICP"})
    assert bad.status == 400
    assert "year" in (await bad.json())["detail"]


async def test_pydantic_integration():
    pydantic = pytest.importorskip("pydantic", reason="pydantic not installed")

    class BookIn(pydantic.BaseModel):
        title: str
        year: int

    adapter = pydantic.TypeAdapter(BookIn)
    app = Hayate()

    @app.post("/books", validator("json", adapter.validate_python))
    async def create(c: Context):
        book = c.req.valid("json")
        return c.json({"title": book.title, "year": book.year}, 201)

    ok = await app.request("/books", method="POST", json={"title": "SICP", "year": 1985})
    assert ok.status == 201
