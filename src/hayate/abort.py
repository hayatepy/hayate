"""Minimal ``AbortSignal``, mirroring the DOM surface a server needs.

``request.signal`` lets handlers observe client disconnects. By default
hayate does not cancel handlers on abort (same safe default as Hono);
cancellation is opt-in via middleware.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

_logger = logging.getLogger("hayate")


class AbortError(Exception):
    """Raised by ``AbortSignal.raise_if_aborted()`` (DOMException "AbortError")."""


class AbortSignal:
    """Fetch ``AbortSignal``: observable cancellation state for a request."""

    __slots__ = ("_aborted", "_callbacks", "_reason")

    def __init__(self) -> None:
        self._aborted = False
        self._reason: Any = None
        self._callbacks: list[Callable[[], None]] = []

    @property
    def aborted(self) -> bool:
        return self._aborted

    @property
    def reason(self) -> Any:
        return self._reason

    def add_listener(self, callback: Callable[[], None]) -> None:
        """Register an abort callback (fires immediately if already aborted)."""
        if self._aborted:
            callback()
            return
        self._callbacks.append(callback)

    def raise_if_aborted(self) -> None:
        """Fetch ``throwIfAborted()``."""
        if self._aborted:
            raise AbortError(self._reason if self._reason is not None else "aborted")

    def _abort(self, reason: Any = None) -> None:
        if self._aborted:
            return
        self._aborted = True
        self._reason = reason
        callbacks, self._callbacks = self._callbacks, []
        for callback in callbacks:
            try:
                callback()
            except Exception:
                _logger.exception("abort listener raised")

    def __repr__(self) -> str:
        return f"AbortSignal(aborted={self._aborted!r})"
