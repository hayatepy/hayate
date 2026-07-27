"""Runtime adapters. The core never imports these at module level."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .asgi import ASGIAdapter, ASGIApplication, ASGIPathDispatcher

__all__ = ["ASGIAdapter", "ASGIApplication", "ASGIPathDispatcher"]


def __getattr__(name: str) -> Any:
    if name in __all__:
        from .asgi import ASGIAdapter, ASGIApplication, ASGIPathDispatcher

        return {
            "ASGIAdapter": ASGIAdapter,
            "ASGIApplication": ASGIApplication,
            "ASGIPathDispatcher": ASGIPathDispatcher,
        }[name]
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def __dir__() -> list[str]:
    return sorted((*globals(), *__all__))
