"""Runtime adapters. The core never imports these at module level."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .asgi import ASGIAdapter

__all__ = ["ASGIAdapter"]


def __getattr__(name: str) -> Any:
    if name == "ASGIAdapter":
        from .asgi import ASGIAdapter

        return ASGIAdapter
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def __dir__() -> list[str]:
    return sorted((*globals(), *__all__))
