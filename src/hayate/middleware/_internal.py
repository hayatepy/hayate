"""Shared helpers for the built-in middleware."""

from __future__ import annotations

from ..headers import Headers


def append_vary(headers: Headers, field: str) -> None:
    """Add a field to ``Vary`` without duplicating existing entries."""
    existing = headers.get("vary")
    if existing is None:
        headers.set("vary", field)
        return
    values = {value.strip().lower() for value in existing.split(",")}
    if "*" in values or field.lower() in values:
        return
    headers.set("vary", f"{existing}, {field}")
