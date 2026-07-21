"""Minimal in-process ASGI WebSocket client for tests."""

from __future__ import annotations

import asyncio
from typing import Any


class WSClient:
    def __init__(self, app: Any, path: str) -> None:
        self.app = app
        self.path = path
        self._to_app: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        self._from_app: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        self._task: asyncio.Task[None] | None = None

    async def __aenter__(self) -> WSClient:
        scope = {
            "type": "websocket",
            "asgi": {"version": "3.0"},
            "scheme": "ws",
            "path": self.path,
            "raw_path": self.path.encode(),
            "query_string": b"",
            "headers": [(b"host", b"testserver")],
            "server": ("testserver", 80),
            "client": ("127.0.0.1", 1),
            "subprotocols": [],
        }
        self._task = asyncio.create_task(self.app(scope, self._to_app.get, self._put))
        await self._to_app.put({"type": "websocket.connect"})
        first = await self.recv()
        assert first == {"type": "websocket.accept"}
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        await self._to_app.put({"type": "websocket.disconnect", "code": 1000})
        assert self._task is not None
        await asyncio.wait_for(self._task, 2)

    async def _put(self, message: dict[str, Any]) -> None:
        await self._from_app.put(message)

    async def send_text(self, text: str) -> None:
        await self._to_app.put({"type": "websocket.receive", "text": text})

    async def send_bytes(self, data: bytes) -> None:
        await self._to_app.put({"type": "websocket.receive", "bytes": data})

    async def recv(self) -> dict[str, Any]:
        return await asyncio.wait_for(self._from_app.get(), 2)

    def nothing_received(self) -> bool:
        return self._from_app.empty()
