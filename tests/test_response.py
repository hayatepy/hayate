"""Response: Fetch semantics with documented Python divergences."""

import pytest

from hayate import Response


async def test_str_body_sets_text_plain():
    res = Response("hi")
    assert res.headers.get("content-type") == "text/plain;charset=utf-8"
    assert await res.text() == "hi"


def test_bytes_body_gets_no_content_type():
    res = Response(b"raw")
    assert res.headers.get("content-type") is None
    assert res.body == b"raw"


def test_explicit_content_type_wins():
    res = Response("<b>x</b>", headers={"content-type": "text/html"})
    assert res.headers.get("content-type") == "text/html"


def test_status_validation():
    with pytest.raises(ValueError):
        Response(None, 99)
    with pytest.raises(ValueError):
        Response(None, 600)


def test_ok_range():
    assert Response(None, 204).ok
    assert not Response(None, 404).ok


def test_redirect():
    res = Response.redirect("/next", 303)
    assert res.status == 303
    assert res.headers.get("location") == "/next"
    with pytest.raises(ValueError):
        Response.redirect("/x", 200)


async def test_json_reader():
    res = Response('{"k": true}')
    assert await res.json() == {"k": True}


async def test_stream_body():
    async def gen():
        yield b"a"
        yield b"b"

    res = Response(gen())
    assert await res.bytes() == b"ab"


def test_invalid_body_type_rejected():
    with pytest.raises(TypeError):
        Response(123)  # type: ignore[arg-type]
