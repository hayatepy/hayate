"""Workers adapter translation logic, tested with faked runtime modules.

Real on-platform verification (Pyodide, streaming, snapshots) is tracked
in docs/research/cloudflare.md §5; these tests pin the FFI translation.
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


@pytest.fixture
def workers_runtime(monkeypatch):
    workers_module = types.ModuleType("workers")
    workers_module.WorkerEntrypoint = FakeWorkerEntrypoint
    workers_module.Response = FakeWorkersResponse
    js_module = types.ModuleType("js")
    js_module.Headers = FakeJsHeadersClass
    monkeypatch.setitem(sys.modules, "workers", workers_module)
    monkeypatch.setitem(sys.modules, "js", js_module)


class FakeJsRequestHeaders:
    def __init__(self, pairs):
        self._pairs = pairs

    def entries(self):
        return [[name, value] for name, value in self._pairs]


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
    """workers-py's Python Request wrapper, as observed on workerd (2026-07):
    the body reader is ``bytes()`` and headers expose ``items()`` —
    neither ``arrayBuffer()`` nor ``entries()`` exists."""

    def __init__(self, url, method="GET", headers=(), body=b""):
        self.url = url
        self.method = method
        self.headers = FakePyRequestHeaders(headers)
        self._body = body

    async def bytes(self):
        return self._body


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
    from hayate.adapters.workers import to_workers

    app = Hayate()

    @app.post("/echo")
    async def echo(c: Context):
        return c.json({"got": await c.req.json()})

    entry = to_workers(app)()
    entry.env = None
    entry.ctx = FakeCtx()

    js_response = await entry.fetch(
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
    from hayate.adapters.workers import to_workers

    app = Hayate()
    entry = to_workers(app)()
    entry.env = None
    entry.ctx = FakeCtx()

    js_response = await entry.fetch(FakeJsRequest("https://edge.example/missing"))
    assert js_response.status == 404
    assert json.loads(js_response.body)["title"] == "Not Found"


async def test_wait_until_bridges_to_js_ctx(workers_runtime):
    from hayate.adapters.workers import to_workers

    app = Hayate()
    done: list[bool] = []

    @app.get("/")
    async def root(c: Context):
        async def background():
            done.append(True)

        c.wait_until(background())
        return c.text("ok")

    entry = to_workers(app)()
    entry.env = None
    entry.ctx = FakeCtx()

    await entry.fetch(FakeJsRequest("https://edge.example/"))
    assert len(entry.ctx.waited) == 1
    await entry.ctx.waited[0]  # workerd awaits the forwarded promise
    assert done == [True]


async def test_streaming_response_is_buffered_for_now(workers_runtime):
    from hayate.adapters.workers import to_workers

    app = Hayate()

    @app.get("/stream")
    async def stream(c: Context):
        async def chunks():
            yield b"a"
            yield b"b"

        return c.body(chunks())

    entry = to_workers(app)()
    entry.env = None
    entry.ctx = FakeCtx()

    js_response = await entry.fetch(FakeJsRequest("https://edge.example/stream"))
    assert js_response.body == b"ab"
