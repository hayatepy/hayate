# Realtime

## WebSocket

Register with `@app.ws`; handlers receive `(c, ws)`. The connection is
accepted automatically on route match, and closing is handled for you.

```python
from hayate import Context, Hayate, WebSocket

app = Hayate()
rooms: dict[str, set[WebSocket]] = {}


@app.ws("/ws/:room")
async def chat(c: Context, ws: WebSocket):
    room = c.req.param("room") or "lobby"
    members = rooms.setdefault(room, set())
    members.add(ws)
    try:
        async for message in ws:          # str | bytes; ends on disconnect
            for member in list(members):
                if member is not ws:
                    await member.send(message)
    finally:
        members.discard(ws)
```

- `await ws.receive()` raises `WebSocketClosed` on disconnect; `async for`
  simply ends.
- `await ws.send(data)` accepts `str` or `bytes`.
- `await ws.close(code, reason)` — called with 1000 automatically when the
  handler returns, 1011 on an unhandled error.
- Route parameters, headers, and cookies are on `c.req` as usual.

The full runnable sample lives at
[`examples/chat.py`](https://github.com/hayatepy/hayate/blob/main/examples/chat.py).

## Server-Sent Events

`c.event_stream()` turns an async iterable of messages into a
`text/event-stream` response (WHATWG HTML format):

```python
@app.get("/events")
async def events(c):
    async def source():
        yield "hello"                                     # data-only
        yield {"event": "update", "id": "42", "data": {"n": 1}}
        yield {"retry": 15000}

    return c.event_stream(source())
```

Messages are dicts with any of `data` / `event` / `id` / `retry`; non-string
`data` is JSON-encoded, multi-line data is split into `data:` lines per the
spec. Consume it from a browser with the standard `EventSource`.
