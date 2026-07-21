"""Server-Sent Events (WHATWG HTML Standard) formatting.

``c.event_stream()`` wraps an async iterable of messages into a
``text/event-stream`` response. A message is either a plain string
(sent as ``data:``) or a mapping with any of the spec's fields:
``data`` (str or JSON-serializable), ``event``, ``id``, ``retry``.
"""

from __future__ import annotations

from collections.abc import AsyncIterable, AsyncIterator, Mapping
from typing import Any

from .jsonutil import dumps_compact

type SSEMessage = str | Mapping[str, Any]


def format_event(message: SSEMessage) -> bytes:
    """Serialize one message per the event stream format."""
    if isinstance(message, str):
        message = {"data": message}
    lines: list[str] = []
    event = message.get("event")
    if event is not None:
        lines.append(f"event: {event}")
    event_id = message.get("id")
    if event_id is not None:
        lines.append(f"id: {event_id}")
    retry = message.get("retry")
    if retry is not None:
        lines.append(f"retry: {int(retry)}")
    data = message.get("data")
    if data is not None:
        if not isinstance(data, str):
            data = dumps_compact(data)
        lines.extend(f"data: {line}" for line in data.split("\n"))
    return ("\n".join(lines) + "\n\n").encode("utf-8")


async def event_stream(source: AsyncIterable[SSEMessage]) -> AsyncIterator[bytes]:
    async for message in source:
        yield format_event(message)
