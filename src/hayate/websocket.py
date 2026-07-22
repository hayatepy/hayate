"""Server-side WebSocket (RFC 6455 over ASGI) with a WHATWG-flavored surface.

v0.2 scope: routes are registered with ``@app.ws(path)`` and handlers
receive ``(c, ws)``; the connection is accepted automatically on route
match. ``send`` / ``receive`` / ``close`` and async iteration are
provided. Subprotocol negotiation is future work.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any


class WebSocketClosed(Exception):
    """Raised by ``receive()`` once the client has disconnected."""

    def __init__(self, code: int = 1005, reason: str = "") -> None:
        super().__init__(f"websocket closed (code={code})")
        self.code = code
        self.reason = reason


class WebSocket:
    """A server-side websocket connection.

    ``send`` / ``receive`` / ``close``, plus async iteration over
    incoming messages.
    """

    __slots__ = ("_accepted", "_closed", "_receive", "_send")

    def __init__(
        self,
        receive: Callable[[], Awaitable[dict[str, Any]]],
        send: Callable[[dict[str, Any]], Awaitable[None]],
    ) -> None:
        self._receive = receive
        self._send = send
        self._accepted = False
        self._closed = False

    async def accept(self) -> None:
        """Complete the handshake (idempotent; the adapter calls this)."""
        if self._accepted:
            return
        message = await self._receive()
        if message["type"] != "websocket.connect":
            raise RuntimeError(f"unexpected websocket message: {message['type']!r}")
        await self._send({"type": "websocket.accept"})
        self._accepted = True

    async def receive(self) -> str | bytes:
        """Next message from the client; raises ``WebSocketClosed`` on disconnect."""
        message = await self._receive()
        kind = message["type"]
        if kind == "websocket.receive":
            text = message.get("text")
            return text if text is not None else message.get("bytes", b"")
        if kind == "websocket.disconnect":
            self._closed = True
            raise WebSocketClosed(message.get("code", 1005))
        raise RuntimeError(f"unexpected websocket message: {kind!r}")

    async def send(self, data: str | bytes) -> None:
        if isinstance(data, str):
            await self._send({"type": "websocket.send", "text": data})
        else:
            await self._send({"type": "websocket.send", "bytes": bytes(data)})

    async def close(self, code: int = 1000, reason: str = "") -> None:
        if self._closed:
            return
        self._closed = True
        await self._send({"type": "websocket.close", "code": code, "reason": reason})

    def __aiter__(self) -> WebSocket:
        return self

    async def __anext__(self) -> str | bytes:
        try:
            return await self.receive()
        except WebSocketClosed:
            raise StopAsyncIteration from None
