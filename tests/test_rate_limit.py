"""rate_limit middleware: draft-ietf-httpapi-ratelimit-headers-11 fields."""

import pytest

from hayate import Context, Hayate
from hayate.middleware import MemoryRateLimitStore, rate_limit


def _app(**options) -> Hayate:
    app = Hayate()
    defaults = {"limit": 2, "window": 60, "key": lambda c: c.req.header("x-client") or "anon"}
    app.use(rate_limit(**{**defaults, **options}))

    @app.get("/data")
    async def data(c: Context):
        return c.json({"ok": True})

    return app


async def test_advertises_quota_and_counts_down():
    app = _app()
    first = await app.request("/data")
    assert first.status == 200
    assert first.headers.get("ratelimit-policy") == '"default";q=2;w=60'
    assert first.headers.get("ratelimit").startswith('"default";r=1;t=')

    second = await app.request("/data")
    assert second.headers.get("ratelimit").startswith('"default";r=0;t=')


async def test_exhaustion_is_429_with_retry_after():
    app = _app()
    await app.request("/data")
    await app.request("/data")
    blocked = await app.request("/data")
    assert blocked.status == 429
    assert blocked.headers.get("retry-after").isdigit()
    assert blocked.headers.get("ratelimit").startswith('"default";r=0;t=')
    assert blocked.headers.get("ratelimit-policy") == '"default";q=2;w=60'
    assert blocked.headers.get("content-type").startswith("application/problem+json")


async def test_partitions_are_independent():
    app = _app()
    for _ in range(2):
        await app.request("/data", headers={"x-client": "a"})
    blocked = await app.request("/data", headers={"x-client": "a"})
    fresh = await app.request("/data", headers={"x-client": "b"})
    assert blocked.status == 429
    assert fresh.status == 200


async def test_window_resets():
    clock = [0.0]
    store = MemoryRateLimitStore(clock=lambda: clock[0])
    app = _app(store=store)
    await app.request("/data")
    await app.request("/data")
    assert (await app.request("/data")).status == 429
    clock[0] = 61.0
    recovered = await app.request("/data")
    assert recovered.status == 200
    assert recovered.headers.get("ratelimit").startswith('"default";r=1;t=')


async def test_none_key_skips_limiting():
    app = _app(key=lambda c: None, limit=1)
    for _ in range(5):
        assert (await app.request("/data")).status == 200
        assert (await app.request("/data")).headers.get("ratelimit") is None


async def test_named_policy():
    app = _app(name="login", limit=1)
    res = await app.request("/data")
    assert res.headers.get("ratelimit-policy") == '"login";q=1;w=60'


def test_invalid_parameters_raise():
    with pytest.raises(ValueError):
        rate_limit(limit=0, window=60, key=lambda c: "x")
    with pytest.raises(ValueError):
        rate_limit(limit=1, window=0, key=lambda c: "x")


async def test_memory_store_sweeps_expired_buckets():
    clock = [0.0]
    store = MemoryRateLimitStore(clock=lambda: clock[0])
    for i in range(5000):
        await store.hit(f"k{i}", 60)
    clock[0] = 120.0
    await store.hit("fresh", 60)
    assert len(store._buckets) < 5000
