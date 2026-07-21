"""Cookies: parsing, Set-Cookie serialization, HMAC signing."""

import pytest

from hayate import Context, Hayate
from hayate.cookies import parse_cookies, serialize_set_cookie, sign_value, unsign_value


def test_parse_first_occurrence_wins():
    assert parse_cookies("a=1; b=2; a=3") == {"a": "1", "b": "2"}
    assert parse_cookies("flag=") == {"flag": ""}


def test_serialize_attributes_in_order():
    value = serialize_set_cookie(
        "sid", "abc", max_age=60, secure=True, http_only=True, same_site="lax"
    )
    assert value == "sid=abc; Max-Age=60; Path=/; Secure; HttpOnly; SameSite=Lax"


def test_host_prefix_requirements():
    with pytest.raises(ValueError):
        serialize_set_cookie("__Host-x", "1")
    ok = serialize_set_cookie("__Host-x", "1", secure=True)
    assert ok.startswith("__Host-x=1")


def test_secure_prefix_requirements():
    with pytest.raises(ValueError):
        serialize_set_cookie("__Secure-x", "1")


def test_samesite_none_requires_secure():
    with pytest.raises(ValueError):
        serialize_set_cookie("a", "1", same_site="none")
    assert "SameSite=None" in serialize_set_cookie("a", "1", same_site="none", secure=True)


def test_invalid_value_rejected():
    with pytest.raises(ValueError):
        serialize_set_cookie("a", "has spaces")


def test_sign_and_unsign():
    signed = sign_value("user42", "secret")
    assert unsign_value(signed, "secret") == "user42"
    assert unsign_value(signed, "other-secret") is None
    assert unsign_value(signed[:-2] + "xx", "secret") is None
    assert unsign_value("no-signature", "secret") is None


async def test_context_cookie_helpers():
    app = Hayate()

    @app.get("/set")
    async def set_cookies(c: Context):
        c.set_cookie("sid", "abc", http_only=True)
        c.set_cookie("theme", "dark")
        return c.text("ok")

    @app.get("/read")
    async def read_cookies(c: Context):
        return c.json(c.req.cookies)

    res = await app.request("/set")
    cookies = res.headers.set_cookie_list()
    assert len(cookies) == 2
    assert cookies[0].startswith("sid=abc")

    res = await app.request("/read", headers={"cookie": "sid=abc; theme=dark"})
    assert await res.json() == {"sid": "abc", "theme": "dark"}
