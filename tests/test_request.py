"""Request: Fetch body semantics, clone/tee, form parsing."""

import pytest

from hayate import File, Request


async def test_body_bytes_and_reuse_forbidden():
    req = Request("http://x/", method="POST", body=b"abc")
    assert not req.body_used
    assert await req.bytes() == b"abc"
    assert req.body_used
    with pytest.raises(TypeError):
        await req.bytes()


async def test_json_body():
    req = Request("http://x/", method="POST", body='{"a": 1}')
    assert await req.json() == {"a": 1}


async def test_text_strips_bom():
    req = Request("http://x/", method="POST", body=b"\xef\xbb\xbfhi")
    assert await req.text() == "hi"


async def test_stream_body_collected():
    async def gen():
        yield b"a"
        yield b"b"

    req = Request("http://x/", method="POST", body=gen())
    assert await req.bytes() == b"ab"


async def test_clone_buffered_both_readable():
    req = Request("http://x/", method="POST", body=b"data")
    other = req.clone()
    assert await req.bytes() == b"data"
    assert await other.bytes() == b"data"


async def test_clone_stream_tees():
    async def gen():
        for chunk in (b"x", b"y", b"z"):
            yield chunk

    req = Request("http://x/", method="POST", body=gen())
    other = req.clone()
    assert await req.bytes() == b"xyz"
    assert await other.bytes() == b"xyz"


async def test_clone_after_use_fails():
    req = Request("http://x/", method="POST", body=b"1")
    await req.bytes()
    with pytest.raises(TypeError):
        req.clone()


async def test_form_urlencoded():
    req = Request(
        "http://x/",
        method="POST",
        headers={"content-type": "application/x-www-form-urlencoded"},
        body="a=1&b=x+y&c=%2F",
    )
    form = await req.form_data()
    assert form.get("a") == "1"
    assert form.get("b") == "x y"
    assert form.get("c") == "/"


async def test_form_multipart():
    boundary = "boundary123"
    body = (
        f"--{boundary}\r\n"
        'Content-Disposition: form-data; name="field"\r\n'
        "\r\n"
        "value\r\n"
        f"--{boundary}\r\n"
        'Content-Disposition: form-data; name="file"; filename="a.txt"\r\n'
        "Content-Type: text/plain\r\n"
        "\r\n"
        "file-content\r\n"
        f"--{boundary}--\r\n"
    ).encode()
    req = Request(
        "http://x/",
        method="POST",
        headers={"content-type": f"multipart/form-data; boundary={boundary}"},
        body=body,
    )
    form = await req.form_data()
    assert form.get("field") == "value"
    upload = form.get("file")
    assert isinstance(upload, File)
    assert upload.name == "a.txt"
    assert upload.type == "text/plain"
    assert upload.size == len(b"file-content")
    assert await upload.bytes() == b"file-content"


async def test_form_data_rejects_other_content_types():
    req = Request(
        "http://x/", method="POST", headers={"content-type": "application/json"}, body="{}"
    )
    with pytest.raises(TypeError):
        await req.form_data()


def test_method_uppercased():
    assert Request("http://x/", method="post").method == "POST"


def test_headers_are_immutable():
    req = Request("http://x/", headers={"a": "1"})
    with pytest.raises(TypeError):
        req.headers.set("a", "2")


def test_default_signal_not_aborted():
    assert Request("http://x/").signal.aborted is False
