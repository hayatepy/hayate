"""Shared helpers for the built-in middleware."""

from __future__ import annotations

from ..headers import Headers


def etag_matches(if_none_match: str, tag: str) -> bool:
    """RFC 9110 §13.1.2 If-None-Match evaluation (weak comparison)."""
    if if_none_match.strip() == "*":
        return True
    normalized = tag.removeprefix("W/")
    return any(
        candidate.strip().removeprefix("W/") == normalized for candidate in if_none_match.split(",")
    )


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
