"""In-process ASGI dispatch benchmark: hayate vs Starlette.

Measures framework overhead only — no sockets, no HTTP parsing. Each
iteration drives one GET request through the framework's ASGI callable
with a no-op transport (fresh scope per request, since frameworks may
mutate it).

Run:

    uv run --group bench python benchmarks/bench.py

Results are recorded in docs/benchmarks.md.
"""

from __future__ import annotations

import asyncio
import platform
import sys
import time
from typing import Any

N = 10_000
ROUNDS = 3
WARMUP = 1_000

_REQUEST = {"type": "http.request", "body": b"", "more_body": False}


def make_scope(path: str) -> dict[str, Any]:
    return {
        "type": "http",
        "asgi": {"version": "3.0", "spec_version": "2.3"},
        "http_version": "1.1",
        "method": "GET",
        "scheme": "http",
        "path": path,
        "raw_path": path.encode(),
        "query_string": b"",
        "root_path": "",
        "headers": [(b"host", b"bench.local"), (b"accept", b"*/*")],
        "server": ("bench.local", 80),
        "client": ("127.0.0.1", 1),
    }


async def _receive() -> dict[str, Any]:
    return _REQUEST


async def _send(message: dict[str, Any]) -> None:
    pass


def build_hayate() -> dict[str, tuple[Any, str]]:
    from hayate import Hayate

    app = Hayate()

    @app.get("/")
    async def home(c):
        return c.text("hello")

    @app.get("/items/:id")
    async def item(c):
        return c.json({"id": c.req.param("id")})

    many = Hayate()
    for index in range(64):

        @many.get(f"/route{index}/:key")
        async def handler(c):
            return c.text("ok")

    mw_app = Hayate()

    @mw_app.use
    async def first(c, next_):
        await next_()

    @mw_app.use
    async def second(c, next_):
        await next_()

    @mw_app.get("/")
    async def mw_home(c):
        return c.text("hello")

    return {
        "static-text": (app, "/"),
        "dynamic-json": (app, "/items/123"),
        "many-routes(64)": (many, "/route63/value"),
        "middleware(2)": (mw_app, "/"),
    }


def build_starlette() -> dict[str, tuple[Any, str]]:
    from starlette.applications import Starlette
    from starlette.responses import JSONResponse, PlainTextResponse
    from starlette.routing import Route

    async def home(request):
        return PlainTextResponse("hello")

    async def item(request):
        return JSONResponse({"id": request.path_params["id"]})

    async def ok(request):
        return PlainTextResponse("ok")

    from starlette.middleware import Middleware as StarletteMiddleware
    from starlette.middleware.base import BaseHTTPMiddleware

    async def passthrough(request, call_next):
        return await call_next(request)

    app = Starlette(routes=[Route("/", home), Route("/items/{id}", item)])
    many = Starlette(routes=[Route(f"/route{i}/{{key}}", ok) for i in range(64)])
    mw_app = Starlette(
        routes=[Route("/", home)],
        middleware=[
            StarletteMiddleware(BaseHTTPMiddleware, dispatch=passthrough),
            StarletteMiddleware(BaseHTTPMiddleware, dispatch=passthrough),
        ],
    )
    return {
        "static-text": (app, "/"),
        "dynamic-json": (app, "/items/123"),
        "many-routes(64)": (many, "/route63/value"),
        "middleware(2)": (mw_app, "/"),
    }


async def bench(app: Any, path: str) -> float:
    """Return best-of-ROUNDS requests/second."""
    for _ in range(WARMUP):
        await app(make_scope(path), _receive, _send)
    best = float("inf")
    for _ in range(ROUNDS):
        start = time.perf_counter()
        for _ in range(N):
            await app(make_scope(path), _receive, _send)
        best = min(best, time.perf_counter() - start)
    return N / best


async def main() -> None:
    import starlette

    import hayate

    print(
        f"python {sys.version.split()[0]} / {platform.machine()} / "
        f"hayate {hayate.__version__} / starlette {starlette.__version__}"
    )
    print(f"N={N}, ROUNDS={ROUNDS} (best round), in-process ASGI, no-op transport\n")
    hayate_apps = build_hayate()
    starlette_apps = build_starlette()
    header = f"{'scenario':<18} {'hayate req/s':>14} {'starlette req/s':>16} {'ratio':>7}"
    print(header)
    print("-" * len(header))
    for name, (h_app, h_path) in hayate_apps.items():
        s_app, s_path = starlette_apps[name]
        h_rps = await bench(h_app, h_path)
        s_rps = await bench(s_app, s_path)
        print(f"{name:<18} {h_rps:>14,.0f} {s_rps:>16,.0f} {h_rps / s_rps:>6.2f}x")


if __name__ == "__main__":
    asyncio.run(main())
