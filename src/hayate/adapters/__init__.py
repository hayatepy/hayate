"""Runtime adapters. The core never imports these at module level."""

from .asgi import ASGIAdapter

__all__ = ["ASGIAdapter"]
