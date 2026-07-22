"""app.routes: the read-only registration ledger for tooling."""

from hayate import Context, Hayate, Route


def _noop_middleware():
    async def mw(c, next_):
        await next_()

    return mw


def test_routes_lists_in_registration_order():
    app = Hayate()
    mw = _noop_middleware()

    @app.get("/static")
    async def static_route(c: Context):
        return c.json({})

    @app.get("/books/:id", mw)
    async def dynamic_route(c: Context):
        return c.json({})

    @app.on("POST", "/api/auth/*")
    async def wildcard_route(c: Context):
        return c.json({})

    routes = app.routes
    assert isinstance(routes, tuple)
    assert all(isinstance(route, Route) for route in routes)
    assert [(r.method, r.pattern) for r in routes] == [
        ("GET", "/static"),
        ("GET", "/books/:id"),
        ("POST", "/api/auth/*"),
    ]
    assert routes[1].middleware == (mw,)
    assert routes[1].handler is not None


def test_routes_is_empty_on_a_fresh_app():
    assert Hayate().routes == ()
