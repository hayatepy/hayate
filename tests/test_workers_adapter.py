"""Workers adapter translation logic, tested with faked runtime modules.

The fakes pin the two request shapes a worker can receive — a raw JS
proxy, and workers-py's Python Request wrapper as read from the SDK
source (workerd src/pyodide/internal/workers-api) and observed on
workerd (2026-07). Real on-platform verification (Pyodide, streaming,
snapshots) is tracked in docs/research/cloudflare.md §5.
"""

import asyncio
import json
import logging
import sys
import types

import pytest

from hayate import Context, Hayate


class FakeJsHeadersClass:
    """Stands in for ``js.Headers``: the constructor takes an init sequence
    of pairs (the adapter crosses the whole header list in one call)."""

    def __init__(self, pairs=None):
        self.pairs: list[tuple[str, str]] = [tuple(pair) for pair in pairs] if pairs else []

    @classmethod
    def new(cls, pairs=None):
        return cls(pairs)

    def append(self, name, value):
        self.pairs.append((name, value))


class FakeWorkersResponse:
    def __init__(self, body, status=200, headers=None, web_socket=None):
        self.body = body
        self.status = status
        self.headers = FakeJsHeadersClass.new(headers) if isinstance(headers, list) else headers
        self.web_socket = web_socket


class FakeWorkerEntrypoint:
    pass


class FakeDurableObject:
    """Stands in for ``workers.DurableObject``."""

    def __init__(self, ctx, env):
        self.ctx = ctx
        self.env = env


class FakeJsWebSocket:
    """One side of a ``WebSocketPair``: records sends, replays events."""

    def __init__(self):
        self.accepted = False
        self.sent = []
        self.closed = None
        self.listeners = {}

    def accept(self):
        self.accepted = True

    def send(self, data):
        self.sent.append(data)

    def close(self, code=1000, reason=""):
        self.closed = (code, reason)

    def addEventListener(self, event, listener):
        self.listeners.setdefault(event, []).append(listener)

    def removeEventListener(self, event, listener):
        self.listeners[event].remove(listener)

    def fire(self, event, payload):
        for listener in list(self.listeners.get(event, [])):
            listener(payload)


class FakeWebSocketPair:
    """``WebSocketPair.new().object_values()`` — the official Python idiom."""

    last = None

    def __init__(self):
        self.client = FakeJsWebSocket()
        self.server = FakeJsWebSocket()
        FakeWebSocketPair.last = self

    @classmethod
    def new(cls):
        return cls()

    def object_values(self):
        return [self.client, self.server]


class FakeJsReadableStream:
    """Stands in for ``js.ReadableStream``: ``from()`` captures the iterable."""

    def __init__(self, iterable):
        self.iterable = iterable

    @classmethod
    def _from(cls, iterable):
        return cls(iterable)


# The adapter looks up the JS static method via getattr (``from`` is a keyword).
setattr(FakeJsReadableStream, "from", FakeJsReadableStream._from)


def _install_runtime(
    monkeypatch,
    *,
    response_cls=FakeWorkersResponse,
    readable_stream=None,
    websocket_pair=None,
):
    workers_module = types.ModuleType("workers")
    workers_module.WorkerEntrypoint = FakeWorkerEntrypoint
    workers_module.DurableObject = FakeDurableObject
    workers_module.Response = response_cls
    workers_module.waited = []
    workers_module.wait_until = workers_module.waited.append
    js_module = types.ModuleType("js")
    js_module.Headers = FakeJsHeadersClass
    if readable_stream is not None:
        js_module.ReadableStream = readable_stream
    if websocket_pair is not None:
        js_module.WebSocketPair = websocket_pair
    monkeypatch.setitem(sys.modules, "workers", workers_module)
    monkeypatch.setitem(sys.modules, "js", js_module)


@pytest.fixture
def workers_runtime(monkeypatch):
    """A runtime without ``js.ReadableStream`` — everything buffers."""
    _install_runtime(monkeypatch)


@pytest.fixture
def workers_streaming_runtime(monkeypatch):
    _install_runtime(monkeypatch, readable_stream=FakeJsReadableStream)


@pytest.fixture
def workers_ws_runtime(monkeypatch):
    _install_runtime(monkeypatch, websocket_pair=FakeWebSocketPair)


class FakeJsRequestHeaders:
    def __init__(self, pairs):
        self._pairs = pairs
        self.reads = 0

    def entries(self):
        self.reads += 1
        return [[name, value] for name, value in self._pairs]


class FakeJsBodyStream:
    """A JS ReadableStream request body: getReader() → read() → {done, value}."""

    def __init__(self, chunks):
        self._chunks = list(chunks)
        self.reads = 0
        self.releases = 0
        self.reader_destroys = 0
        self.stream_destroys = 0
        self.result_destroys = 0

    def getReader(self):
        return FakeJsBodyReader(self)

    def destroy(self):
        self.stream_destroys += 1


class FakeJsReadResult:
    def __init__(self, owner, *, done, value):
        self._owner = owner
        self.done = done
        self.value = value

    def destroy(self):
        self._owner.result_destroys += 1


class FakeJsBodyReader:
    def __init__(self, owner):
        self._owner = owner

    async def read(self):
        self._owner.reads += 1
        if not self._owner._chunks:
            return FakeJsReadResult(self._owner, done=True, value=None)
        return FakeJsReadResult(self._owner, done=False, value=self._owner._chunks.pop(0))

    def releaseLock(self):
        self._owner.releases += 1

    def destroy(self):
        self._owner.reader_destroys += 1


class FakeJsAbortSignal:
    def __init__(self, aborted=False, reason=None):
        self.aborted = aborted
        self.reason = reason
        self.listeners = []
        self.adds = 0

    def addEventListener(self, event, listener):
        assert event == "abort"
        self.adds += 1
        self.listeners.append(listener)

    def removeEventListener(self, event, listener):
        assert event == "abort"
        self.listeners.remove(listener)

    def fire(self, reason=None):
        self.aborted = True
        self.reason = reason
        for listener in self.listeners:
            listener()


class FakeJsRequest:
    def __init__(self, url, method="GET", headers=(), body=None):
        self.url = url
        self.method = method
        self.headers = FakeJsRequestHeaders(headers)
        self.body = body
        self.text_reads = 0

    async def arrayBuffer(self):
        return memoryview(self.body or b"")

    async def text(self):
        self.text_reads += 1
        if isinstance(self.body, FakeJsBodyStream):
            chunks, self.body._chunks = self.body._chunks, []
            return b"".join(chunks).decode()
        return bytes(self.body or b"").decode()


class FakeCtx:
    def __init__(self):
        self.waited = []

    def waitUntil(self, promise):
        self.waited.append(promise)


class FakePyRequestHeaders:
    """workers-py wrapper shape: a Mapping with ``items()``."""

    def __init__(self, pairs):
        self._pairs = pairs

    def items(self):
        return list(self._pairs)


class FakePyRequest:
    """workers-py's Python Request wrapper, as pinned from the SDK source:
    the body reader is ``bytes()``, headers expose ``items()``, the raw JS
    request sits on ``js_object`` (the only place ``signal`` lives), and
    ``body`` forwards ``js_object.body`` — neither ``arrayBuffer()`` nor
    ``headers.entries()`` exists."""

    def __init__(self, url, method="GET", headers=(), body=b"", js_object=None):
        self.url = url
        self.method = method
        self.headers = FakePyRequestHeaders(headers)
        self._body = body
        self.js_object = js_object

    @property
    def body(self):
        return None if self.js_object is None else self.js_object.body

    async def bytes(self):
        return self._body


def _entry(app):
    from hayate.adapters.workers import to_workers

    entry = to_workers(app)()
    entry.env = None
    entry.ctx = FakeCtx()
    return entry


async def test_fetch_roundtrip(workers_runtime):
    from hayate.adapters.workers import to_workers

    app = Hayate()

    @app.post("/echo/:name")
    async def echo(c: Context):
        payload = await c.req.json()
        return c.json({"name": c.req.param("name"), "got": payload, "binding": c.env["KV"]})

    entry = to_workers(app)()
    entry.env = {"KV": "bound"}
    entry.ctx = FakeCtx()

    js_response = await entry.fetch(
        FakeJsRequest(
            "https://edge.example/echo/hayate",
            method="POST",
            headers=[("content-type", "application/json")],
            body=b'{"x": 1}',
        )
    )
    assert js_response.status == 200
    assert json.loads(js_response.body) == {
        "name": "hayate",
        "got": {"x": 1},
        "binding": "bound",
    }
    assert ("content-type", "application/json") in js_response.headers.pairs


async def test_request_id_and_final_access_log_cross_native_workers_adapter(
    workers_runtime,
    caplog,
):
    from hayate.middleware import current_request_id, logger, request_id

    app = Hayate()
    app.use(request_id())
    app.use(logger(structured=True))
    seen: list[str | None] = []

    @app.get("/")
    async def root(c: Context):
        seen.append(current_request_id())
        return c.text(c.get("request_id"))

    with caplog.at_level(logging.INFO, logger="hayate.request"):
        js_response = await _entry(app).fetch(
            FakeJsRequest(
                "https://edge.example/",
                headers=[("x-request-id", "workerd-request-123")],
            )
        )

    assert js_response.body == b"workerd-request-123"
    assert ("x-request-id", "workerd-request-123") in js_response.headers.pairs
    assert seen == ["workerd-request-123"]
    assert current_request_id() is None
    event = json.loads(
        next(record.getMessage() for record in caplog.records if record.name == "hayate.request")
    )
    assert (event["status"], event["request_id"]) == (200, "workerd-request-123")


async def test_fetch_runs_route_middleware_without_global_middleware(workers_runtime):
    app = Hayate()
    calls = []

    async def route_middleware(c, next_):
        calls.append("before")
        await next_()
        calls.append("after")

    @app.get("/", route_middleware)
    async def root(c: Context):
        calls.append("handler")
        return c.text("ok")

    js_response = await _entry(app).fetch(FakeJsRequest("https://edge.example/"))

    assert js_response.status == 200
    assert js_response.body == b"ok"
    assert calls == ["before", "handler", "after"]


class FakeLegacyPyRequest:
    """A wrapper shape that does not forward ``body`` at all — the adapter
    must take the buffered fallback and read via ``bytes()``."""

    def __init__(self, url, method="GET", headers=(), body=b""):
        self.url = url
        self.method = method
        self.headers = FakePyRequestHeaders(headers)
        self._body = body

    async def bytes(self):
        return self._body


async def test_workers_py_wrapper_shape(workers_runtime):
    """Regression: workerd hands us the workers-py wrapper, not a JS proxy."""
    app = Hayate()

    @app.post("/echo")
    async def echo(c: Context):
        return c.json({"got": await c.req.json()})

    js_response = await _entry(app).fetch(
        FakeLegacyPyRequest(
            "https://edge.example/echo",
            method="POST",
            headers=[("content-type", "application/json")],
            body=b'{"k": 1}',
        )
    )
    assert js_response.status == 200
    assert json.loads(js_response.body) == {"got": {"k": 1}}


async def test_get_has_null_body_and_problem_details_work(workers_runtime):
    app = Hayate()
    js_response = await _entry(app).fetch(FakeJsRequest("https://edge.example/missing"))
    assert js_response.status == 404
    assert json.loads(js_response.body)["title"] == "Not Found"


async def test_wait_until_bridges_to_js_ctx(workers_runtime):
    app = Hayate()
    done: list[bool] = []

    @app.get("/")
    async def root(c: Context):
        async def background():
            done.append(True)

        c.wait_until(background())
        return c.text("ok")

    entry = _entry(app)
    await entry.fetch(FakeJsRequest("https://edge.example/"))
    assert len(entry.ctx.waited) == 1
    await entry.ctx.waited[0]  # workerd awaits the forwarded promise
    assert done == [True]


async def test_global_handler_uses_importable_wait_until(workers_runtime):
    from hayate.adapters.workers import to_workers_global

    app = Hayate()
    done = []

    @app.get("/")
    async def root(c: Context):
        async def background():
            done.append(True)

        c.wait_until(background())
        return c.text("ok")

    handler = to_workers_global(app)
    response = await handler(FakeJsRequest("https://edge.example/"), {"KV": "bound"})

    assert response.status == 200
    assert len(sys.modules["workers"].waited) == 1
    await sys.modules["workers"].waited[0]
    assert done == [True]


def test_global_handler_returns_inline_response_without_coroutine(workers_runtime, monkeypatch):
    app_module = __import__("hayate.app", fromlist=["_INLINE_SYNC_HANDLERS"])
    monkeypatch.setattr(app_module, "_INLINE_SYNC_HANDLERS", True)
    from hayate.adapters.workers import to_workers_global

    app = Hayate()

    @app.get("/")
    def root(c: Context):
        return c.text("inline")

    response = to_workers_global(app)(FakeJsRequest("https://edge.example/"), {"KV": "bound"})

    assert isinstance(response, FakeWorkersResponse)
    assert response.body == b"inline"


def test_class_entrypoint_returns_inline_response_without_coroutine(workers_runtime, monkeypatch):
    app_module = __import__("hayate.app", fromlist=["_INLINE_SYNC_HANDLERS"])
    monkeypatch.setattr(app_module, "_INLINE_SYNC_HANDLERS", True)
    app = Hayate()

    @app.get("/")
    def root(c: Context):
        return c.text("inline")

    response = _entry(app).fetch(FakeJsRequest("https://edge.example/"))

    assert isinstance(response, FakeWorkersResponse)
    assert response.body == b"inline"


def _streaming_app():
    app = Hayate()

    @app.get("/stream")
    async def stream(c: Context):
        async def chunks():
            yield b"a"
            yield b"b"

        return c.body(chunks())

    return app


async def test_streaming_response_buffers_without_readable_stream(workers_runtime):
    """A runtime without ``js.ReadableStream`` gets the buffered fallback."""
    js_response = await _entry(_streaming_app()).fetch(FakeJsRequest("https://edge.example/stream"))
    assert js_response.body == b"ab"


async def test_direct_js_response_reuses_options_and_releases_body_proxy(monkeypatch):
    """The Pyodide fast path bypasses the SDK wrapper without leaking proxies."""
    _install_runtime(monkeypatch)
    from hayate.adapters import workers as adapter

    class Converted:
        def __init__(self, value):
            self.value = value
            self.destroys = 0

        def destroy(self):
            self.destroys += 1

    converted = []

    def fake_to_js(value, *, dict_converter=None):
        if isinstance(value, dict):
            assert dict_converter is FakeObject.fromEntries
        result = Converted(value)
        converted.append(result)
        return result

    class FakeObject:
        @staticmethod
        def fromEntries(value):
            return value

    class FakeDirectResponse:
        @classmethod
        def new(cls, body, options):
            value = body.value if isinstance(body, Converted) else body
            response = FakeWorkersResponse(
                value,
                status=options.value["status"],
                headers=options.value["headers"],
            )
            response.options = options
            return response

    js_module = sys.modules["js"]
    js_module.Object = FakeObject
    js_module.Response = FakeDirectResponse
    monkeypatch.setattr(adapter, "_to_js", fake_to_js)

    app = Hayate()

    @app.get("/")
    async def root(c: Context):
        return c.body(b"ok")

    @app.get("/text")
    async def text(c: Context):
        return c.text("hello")

    entry = _entry(app)
    first = await entry.fetch(FakeJsRequest("https://edge.example/"))
    second = await entry.fetch(FakeJsRequest("https://edge.example/"))
    text_response = await entry.fetch(FakeJsRequest("https://edge.example/text"))

    assert first.body == second.body == b"ok"
    assert text_response.body == "hello"
    assert first.options is second.options
    assert first.options.destroys == 0
    assert [proxy.destroys for proxy in converted if isinstance(proxy.value, bytes)] == [1, 1]

    runtime = adapter._Runtime()
    options = [runtime.response_options(200, [("x-response", str(index))]) for index in range(129)]
    assert len(runtime._response_options) == 128
    assert options[0].destroys == 1
    assert all(option.destroys == 0 for option in options[1:])

    shared_pairs = (("content-type", "application/json"),)
    shared_options = runtime.response_options(200, shared_pairs)
    assert runtime.response_options(200, shared_pairs) is shared_options
    assert runtime._last_response_pairs is shared_pairs


async def test_streaming_response_becomes_a_readable_stream(workers_streaming_runtime):
    js_response = await _entry(_streaming_app()).fetch(FakeJsRequest("https://edge.example/stream"))
    assert js_response.status == 200
    assert isinstance(js_response.body, FakeJsReadableStream)
    # Chunks stay raw bytes here: outside Pyodide there is no to_js().
    assert [chunk async for chunk in js_response.body.iterable] == [b"a", b"b"]


async def test_sse_streams_as_a_readable_stream(workers_streaming_runtime):
    app = Hayate()

    @app.get("/events")
    async def events(c: Context):
        async def source():
            yield {"data": "tick"}

        return c.event_stream(source())

    js_response = await _entry(app).fetch(FakeJsRequest("https://edge.example/events"))
    assert isinstance(js_response.body, FakeJsReadableStream)
    payload = b"".join([chunk async for chunk in js_response.body.iterable])
    assert b"data: tick" in payload
    assert ("content-type", "text/event-stream") in js_response.headers.pairs


async def test_streaming_falls_back_when_the_sdk_rejects_streams(monkeypatch):
    """An SDK without ReadableStream in its accepted body types buffers."""

    class RejectingResponse(FakeWorkersResponse):
        def __init__(self, body, status=200, headers=None):
            if isinstance(body, FakeJsReadableStream):
                raise TypeError("Unsupported type in Response: ReadableStream")
            super().__init__(body, status=status, headers=headers)

    _install_runtime(
        monkeypatch, response_cls=RejectingResponse, readable_stream=FakeJsReadableStream
    )
    js_response = await _entry(_streaming_app()).fetch(FakeJsRequest("https://edge.example/stream"))
    assert js_response.body == b"ab"


async def test_request_stream_body_is_bridged_not_buffered(workers_runtime):
    app = Hayate()

    @app.post("/echo")
    async def echo(c: Context):
        body = c.req.raw.body
        assert body is not None
        payload = b"".join([chunk async for chunk in body])
        return c.json({"got": json.loads(payload)})

    request = FakeJsRequest(
        "https://edge.example/echo",
        method="POST",
        headers=[("content-type", "application/json")],
    )
    stream = FakeJsBodyStream([b'{"k"', b": 1}"])
    request.body = stream

    async def fail_buffered_read():
        raise AssertionError("a stream body must not be read via arrayBuffer()")

    request.arrayBuffer = fail_buffered_read

    js_response = await _entry(app).fetch(request)
    assert json.loads(js_response.body) == {"got": {"k": 1}}
    assert stream.reads == 3  # two chunks + the done signal
    assert stream.releases == 1
    assert stream.result_destroys == 3
    assert stream.reader_destroys == 1
    assert stream.stream_destroys == 1
    assert request.text_reads == 0


async def test_wrapper_streams_body_and_bridges_signal_via_js_object(workers_streaming_runtime):
    """The wrapper's ``js_object`` is the escape hatch for body and signal.

    The abort must be visible while the response is still streaming, and
    the JS listener must be released once the stream has finished.
    """
    app = Hayate()

    @app.post("/echo")
    async def echo(c: Context):
        await c.req.json()  # the body arrives over the js_object stream
        signal = c.req.signal

        async def chunks():
            yield f"start aborted={signal.aborted}".encode()
            yield f" end aborted={signal.aborted} reason={signal.reason}".encode()

        return c.body(chunks())

    js_signal = FakeJsAbortSignal()
    raw_request = FakeJsRequest(
        "https://edge.example/echo",
        method="POST",
        headers=[("content-type", "application/json")],
        body=FakeJsBodyStream([b'{"k": 1}']),
    )
    raw_request.signal = js_signal
    wrapper = FakePyRequest(
        "https://edge.example/echo",
        method="POST",
        headers=[("content-type", "application/json")],
        js_object=raw_request,
    )

    js_response = await _entry(app).fetch(wrapper)
    iterator = js_response.body.iterable.__aiter__()
    first = await iterator.__anext__()
    assert first == b"start aborted=False"
    js_signal.fire("client went away")  # disconnect mid-stream
    rest = b"".join([chunk async for chunk in iterator])
    assert rest == b" end aborted=True reason=client went away"
    assert raw_request.text_reads == 1
    assert js_signal.listeners == []  # released deterministically after the stream


async def test_already_aborted_signal_is_mirrored(workers_runtime):
    app = Hayate()

    @app.get("/")
    async def root(c: Context):
        return c.json({"aborted": c.req.signal.aborted, "reason": c.req.signal.reason})

    request = FakeJsRequest("https://edge.example/")
    request.signal = FakeJsAbortSignal(aborted=True, reason="boom")

    js_response = await _entry(app).fetch(request)
    assert json.loads(js_response.body) == {"aborted": True, "reason": "boom"}


async def test_bodyless_requests_skip_the_buffered_read(workers_runtime):
    """Fetch GET/HEAD never read ``body`` or use the buffered FFI crossing."""
    app = Hayate()

    @app.get("/")
    async def root(c: Context):
        return c.text("ok")

    raw = FakeJsRequest("https://edge.example/")

    async def fail_read():
        raise AssertionError("a bodyless request must not be read via arrayBuffer()")

    raw.arrayBuffer = fail_read

    class ExplodingBodyRequest(FakeJsRequest):
        @property
        def body(self):
            raise AssertionError("GET must not cross the JS body property")

        @body.setter
        def body(self, value):
            pass

    class ExplodingBytesPyRequest(FakePyRequest):
        async def bytes(self):
            raise AssertionError("a bodyless request must not be read via bytes()")

    wrapper = ExplodingBytesPyRequest(
        "https://edge.example/",
        js_object=FakeJsRequest("https://edge.example/"),
    )

    assert (await _entry(app).fetch(raw)).status == 200
    assert raw.headers.reads == 0
    assert (await _entry(app).fetch(ExplodingBodyRequest("https://edge.example/"))).status == 200
    assert (await _entry(app).fetch(wrapper)).status == 200


async def test_http_only_app_skips_headers_with_websocket_runtime(workers_ws_runtime):
    """The presence of WebSocketPair alone must not force Upgrade inspection."""
    app = Hayate()

    @app.get("/")
    async def root(c: Context):
        return c.text("ok")

    request = FakeJsRequest("https://edge.example/")
    assert (await _entry(app).fetch(request)).status == 200
    assert request.headers.reads == 0


async def test_workers_http_method_enum_shape_is_normalized(workers_runtime):
    """workers-py returns an enum on some Pyodide builds and a string on others."""
    app = Hayate()

    @app.get("/")
    async def root(c: Context):
        return c.text("ok")

    class EnumLikeGet:
        value = "GET"

        def __str__(self):
            return "HTTPMethod.GET"

    request = FakeJsRequest("https://edge.example/")
    request.method = EnumLikeGet()

    assert (await _entry(app).fetch(request)).status == 200


async def test_null_body_statuses_cross_without_a_body(workers_runtime):
    """Fetch null-body statuses (204/304/...) must not carry a body —
    ``js.Response`` would throw on them."""
    app = Hayate()

    @app.get("/cached")
    async def cached(c: Context):
        return c.body(b"stale bytes a middleware left behind", status=304)

    js_response = await _entry(app).fetch(FakeJsRequest("https://edge.example/cached"))
    assert js_response.status == 304
    assert js_response.body is None


def test_trusted_url_split_matches_the_full_parser():
    from hayate import URL
    from hayate.adapters.workers import _url_from_trusted

    hrefs = [
        "https://edge.example/echo/hayate?x=1&y=%20z",
        "http://localhost:8787/",
        "https://edge.example",
        "https://edge.example:8443/a/b/../c?q",
        "https://user:pw@edge.example/keeps-working",  # falls back to the parser
        "https://edge.example/path#frag",  # fragments never arrive; fallback
    ]
    components = ("protocol", "hostname", "port", "pathname", "search", "hash")
    for href in hrefs:
        fast, full = _url_from_trusted(href), URL(href)
        for component in components:
            assert getattr(fast, component) == getattr(full, component), (href, component)


async def test_abort_listener_is_released_after_a_buffered_response(workers_runtime):
    """No reliance on FinalizationRegistry: the listener is removed at once."""
    app = Hayate()

    @app.get("/")
    async def root(c: Context):
        return c.text("ok")

    request = FakeJsRequest("https://edge.example/")
    request.signal = FakeJsAbortSignal()

    await _entry(app).fetch(request)
    assert request.signal.adds == 0
    assert request.signal.listeners == []


def _ws_upgrade_request(url="https://edge.example/ws"):
    return FakeJsRequest(url, headers=[("connection", "Upgrade"), ("upgrade", "websocket")])


async def test_websocket_upgrade_serves_the_ws_route(workers_ws_runtime):
    """An ``@app.ws()`` handler runs unchanged over a ``WebSocketPair``."""
    from hayate.adapters.workers import _live_connections

    app = Hayate()

    @app.ws("/ws/:room")
    async def echo(c: Context, ws):
        await ws.send(f"joined {c.req.param('room')}")
        async for message in ws:
            await ws.send(message)

    js_response = _entry(app).fetch(_ws_upgrade_request("https://edge.example/ws/lobby"))
    pair = FakeWebSocketPair.last

    assert js_response.status == 101
    assert js_response.web_socket is pair.client
    assert pair.server.accepted
    task = next(iter(_live_connections))

    pair.server.fire("message", types.SimpleNamespace(data="hi"))
    pair.server.fire("message", types.SimpleNamespace(data=b"\x01\x02"))
    pair.server.fire("close", types.SimpleNamespace(code=1000, reason=""))
    await asyncio.wait_for(task, 1)

    assert pair.server.sent == ["joined lobby", "hi", b"\x01\x02"]
    assert all(not registered for registered in pair.server.listeners.values())


async def test_websocket_handler_error_closes_with_1011(workers_ws_runtime):
    from hayate.adapters.workers import _live_connections

    app = Hayate()

    @app.ws("/ws")
    async def boom(c: Context, ws):
        raise RuntimeError("handler bug")

    _entry(app).fetch(_ws_upgrade_request())
    pair = FakeWebSocketPair.last
    await asyncio.wait_for(next(iter(_live_connections)), 1)

    assert pair.server.closed == (1011, "internal error")
    assert all(not registered for registered in pair.server.listeners.values())


async def test_upgrade_without_a_ws_route_falls_through_to_http(workers_ws_runtime):
    app = Hayate()
    js_response = await _entry(app).fetch(_ws_upgrade_request("https://edge.example/nope"))
    assert js_response.status == 404
    assert json.loads(js_response.body)["title"] == "Not Found"


class FakeStorage:
    """``ctx.storage`` — the async KV surface of DurableObjectStorage."""

    def __init__(self):
        self.data = {}

    async def get(self, key):
        return self.data.get(key)

    async def put(self, key, value):
        self.data[key] = value


def _counter_factory(ctx, env):
    app = Hayate()

    @app.get("/count")
    async def count(c: Context):
        n = int((await ctx.storage.get("n")) or 0) + 1
        await ctx.storage.put("n", n)
        return c.json({"count": n, "binding": c.env["KV"]})

    return app


async def test_durable_object_mounts_a_hayate_app(workers_runtime):
    """``to_durable_object``: routes read the object's storage via closure."""
    from hayate.adapters.workers import to_durable_object

    counter_cls = to_durable_object(_counter_factory)
    # workerd registers Durable Object classes by __name__, not by the
    # module attribute they are assigned to (introspection.py) — the
    # factory's name is the exported class name.
    assert counter_cls.__name__ == "_counter_factory"
    ctx = types.SimpleNamespace(storage=FakeStorage())
    obj = counter_cls(ctx, {"KV": "bound"})

    first = await obj.fetch(FakeJsRequest("https://do.example/count"))
    second = await obj.fetch(FakeJsRequest("https://do.example/count"))

    assert json.loads(first.body) == {"count": 1, "binding": "bound"}
    assert json.loads(second.body) == {"count": 2, "binding": "bound"}
    assert obj.ctx is ctx  # the DurableObject base-class contract


class FakeFetcherStub:
    """A Durable Object stub / service binding: records what it was fed."""

    def __init__(self, response):
        self.response = response
        self.received = None

    async def fetch(self, request):
        self.received = request
        return self.response


async def test_forward_returns_the_platform_response_untouched(workers_runtime):
    from hayate.adapters.workers import forward

    platform_response = types.SimpleNamespace(status=101, web_socket="the-client-socket")
    stub = FakeFetcherStub(platform_response)
    app = Hayate()

    @app.get("/room/:name")
    async def room(c: Context):
        return await forward(c, stub)

    raw_js = FakeJsRequest(
        "https://edge.example/room/lobby",
        headers=[("connection", "Upgrade"), ("upgrade", "websocket")],
    )
    request = FakePyRequest(
        "https://edge.example/room/lobby",
        headers=[("connection", "Upgrade"), ("upgrade", "websocket")],
        js_object=raw_js,
    )

    result = await _entry(app).fetch(request)
    # Identity, not equality: platform extensions (webSocket) must survive.
    assert result is platform_response
    assert stub.received is raw_js  # the *original* platform request was forwarded


async def test_forward_outside_the_workers_adapter_is_an_error():
    from hayate.adapters.workers import forward

    app = Hayate()

    @app.get("/room")
    async def room(c: Context):
        return await forward(c, FakeFetcherStub(None))

    response = await app.request("/room")
    assert response.status == 500  # RuntimeError -> problem+json


async def test_durable_object_serves_websocket_routes(workers_ws_runtime):
    from hayate.adapters.workers import to_durable_object

    def build(ctx, env):
        app = Hayate()

        @app.ws("/ws")
        async def echo(c: Context, ws):
            async for message in ws:
                await ws.send(message)

        return app

    obj = to_durable_object(build)(types.SimpleNamespace(storage=FakeStorage()), None)
    js_response = obj.fetch(_ws_upgrade_request("https://do.example/ws"))
    assert js_response.status == 101
    assert js_response.web_socket is FakeWebSocketPair.last.client
