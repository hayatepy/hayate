"""Realtime chat over WebSocket — the v0.2 acceptance sample.

Run:

    uv run --with uvicorn uvicorn chat:app --app-dir examples

then open http://127.0.0.1:8000/ in two tabs.
"""

from __future__ import annotations

from hayate import Context, Hayate, WebSocket

app = Hayate()

rooms: dict[str, set[WebSocket]] = {}

INDEX_HTML = """<!doctype html>
<meta charset="utf-8">
<title>hayate chat</title>
<input id="msg" placeholder="type and press enter">
<pre id="log"></pre>
<script>
  const room = new URLSearchParams(location.search).get("room") ?? "lobby";
  const ws = new WebSocket(`ws://${location.host}/ws/${room}`);
  const log = (line) => document.getElementById("log").append(line + "\\n");
  ws.onmessage = (event) => log(event.data);
  document.getElementById("msg").addEventListener("keydown", (event) => {
    if (event.key === "Enter" && event.target.value) {
      ws.send(event.target.value);
      log("me: " + event.target.value);
      event.target.value = "";
    }
  });
</script>
"""


@app.get("/")
async def index(c: Context):
    return c.html(INDEX_HTML)


@app.ws("/ws/:room")
async def chat(c: Context, ws: WebSocket):
    room = c.req.param("room") or "lobby"
    members = rooms.setdefault(room, set())
    members.add(ws)
    try:
        async for message in ws:
            if isinstance(message, str):
                for member in list(members):
                    if member is not ws:
                        await member.send(message)
    finally:
        members.discard(ws)
        if not members:
            rooms.pop(room, None)
