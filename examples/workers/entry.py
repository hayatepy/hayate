"""Cloudflare Python Workers entry for the hayate example.

Deploy (from this directory, wrangler + Python Workers beta):

    uv run pywrangler dev      # local workerd
    uv run pywrangler deploy   # to Cloudflare
"""

from hayate import Context, Hayate
from hayate.adapters.workers import to_workers

app = Hayate()


@app.get("/")
async def hello(c: Context):
    return c.json(
        {
            "framework": "hayate",
            "runtime": "cloudflare-python-workers",
            "url": c.req.url.href,
        }
    )


@app.get("/hello/:name")
async def greet(c: Context):
    return c.json({"hello": c.req.param("name")})


Default = to_workers(app)
