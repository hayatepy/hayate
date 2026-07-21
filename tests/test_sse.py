"""Server-Sent Events formatting and the c.event_stream helper."""

from hayate import Context, Hayate
from hayate.sse import format_event


def test_format_plain_string():
    assert format_event("x") == b"data: x\n\n"


def test_format_multiline_data():
    assert format_event({"data": "a\nb"}) == b"data: a\ndata: b\n\n"


def test_format_full_event():
    encoded = format_event({"event": "update", "id": "42", "retry": 1500, "data": {"n": 1}})
    assert encoded == b'event: update\nid: 42\nretry: 1500\ndata: {"n":1}\n\n'


async def test_event_stream_response():
    app = Hayate()

    @app.get("/events")
    async def events(c: Context):
        async def source():
            yield "hello"
            yield {"event": "update", "data": {"n": 1}}

        return c.event_stream(source())

    res = await app.request("/events")
    assert res.headers.get("content-type") == "text/event-stream"
    assert res.headers.get("cache-control") == "no-cache"
    payload = (await res.bytes()).decode()
    assert "data: hello\n\n" in payload
    assert 'event: update\ndata: {"n":1}\n\n' in payload
