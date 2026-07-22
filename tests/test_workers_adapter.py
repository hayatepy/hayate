"""Workers adapter translation logic, tested with faked runtime modules.

The fakes pin the two request shapes a worker can receive — a raw JS
proxy, and workers-py's Python Request wrapper as read from the SDK
source (workerd src/pyodide/internal/workers-api) and observed on
workerd (2026-07). Real on-platform verification (Pyodide, streaming,
snapshots) is tracked in docs/research/cloudflare.md §5.
"""

import json
import sys
import types

import pytest

from hayate import Context, Hayate


class FakeJsHeadersClass:
    """Stands in for ``js.Headers`` (JsProxy constructor style: ``.new()``)."""

    def __init__(self):
        self.pairs: list[tuple[str, str]] = []

    @classmethod
    def new(cls):
        return cls()

    def append(self, name, value):
        self.pairs.append((name, value))


class FakeWorkersResponse:
    def __init__(self, body, status=200, headers=None):
        self.body = body
        self.status = status
        self.headers = headers


class FakeWorkerEntrypoint:
    pass


class FakeJsReadableStream:
    """Stands in for ``js.ReadableStream``: ``from()`` captures the iterable."""

    def __init__(self, iterable):
        self.iterable = iterable

    @classmethod
    def _from(cls, iterable):
        return cls(iterable)


# The adapter looks up the JS static method via getattr (``from`` is a keyword).
setattr(FakeJsReadableStream, "from", FakeJsReadableStream._from)


def _install_runtime(monkeypatch, *, response_cls=FakeWorkersResponse, readable_stream=None):
    workers_module = types.ModuleType("workers")
    workers_module.WorkerEntrypoint = FakeWorkerEntrypoint
    workers_module.Response = response_cls
    js_module = types.ModuleType("js")
    js_module.Headers = FakeJsHeadersClass
    if readable_stream is not None:
        js_module.ReadableStream = readable_stream
    monkeypatch.setitem(sys.modules, "workers", workers_module)
    monkeypatch.setitem(sys.modules, "js", js_module)


@pytest.fixture
def workers_runtime(monkeypatch):
    """A runtime without ``js.ReadableStream`` — everything buffers."""
    _install_runtime(monkeypatch)


@pytest.fixture
def workers_streaming_runtime(monkeypatch):
    _install_runtime(monkeypatch, readable_stream=FakeJsReadableStream)


class FakeJsRequestHeaders:
    def __init__(self, pairs):
        self._pairs = pairs

    def entries(self):
        return [[name, value] for name, value in self._pairs]


class FakeJsBodyStream:
    """A JS ReadableStream request body: getReader() → read() → {done, value}."""

    def __init__(self, chunks):
        self._chunks = list(chunks)
        self.reads = 0

    def getReader(self):
        return self

    async def read(self):
        self.reads += 1
        if not self._chunks:
            return types.SimpleNamespace(done=True, value=None)
        return types.SimpleNamespace(done=False, value=self._chunks.pop(0))


class FakeJsAbortSignal:
    def __init__(self, aborted=False, reason=None):
        self.aborted = aborted
        self.reason = reason
        self.listeners = []

    def addEventListener(self, event, listener):
        assert event == "abort"
        self.listeners.append(listener)

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

    async def arrayBuffer(self):
        return memoryview(self.body or b"")


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


async def test_workers_py_wrapper_shape(workers_runtime):
    """Regression: workerd hands us the workers-py wrapper, not a JS proxy."""
    app = Hayate()

    @app.post("/echo")
    async def echo(c: Context):
        return c.json({"got": await c.req.json()})

    js_response = await _entry(app).fetch(
        FakePyRequest(
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
        return c.json({"got": await c.req.json()})

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


async def test_wrapper_streams_body_and_bridges_signal_via_js_object(workers_runtime):
    """The wrapper's ``js_object`` is the escape hatch for body and signal."""
    app = Hayate()
    seen = {}

    @app.post("/echo")
    async def echo(c: Context):
        seen["signal"] = c.req.signal
        return c.json({"got": await c.req.json()})

    js_signal = FakeJsAbortSignal()
    wrapper = FakePyRequest(
        "https://edge.example/echo",
        method="POST",
        headers=[("content-type", "application/json")],
        js_object=types.SimpleNamespace(body=FakeJsBodyStream([b'{"k": 1}']), signal=js_signal),
    )

    js_response = await _entry(app).fetch(wrapper)
    assert json.loads(js_response.body) == {"got": {"k": 1}}
    assert seen["signal"].aborted is False

    js_signal.fire("client went away")  # disconnect after the response
    assert seen["signal"].aborted is True
    assert seen["signal"].reason == "client went away"


async def test_already_aborted_signal_is_mirrored(workers_runtime):
    app = Hayate()

    @app.get("/")
    async def root(c: Context):
        return c.json({"aborted": c.req.signal.aborted, "reason": c.req.signal.reason})

    request = FakeJsRequest("https://edge.example/")
    request.signal = FakeJsAbortSignal(aborted=True, reason="boom")

    js_response = await _entry(app).fetch(request)
    assert json.loads(js_response.body) == {"aborted": True, "reason": "boom"}
