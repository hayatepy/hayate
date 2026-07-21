"""Method x pathname routing table.

v0.1 strategy (single code path; optimize when benchmarks demand it):
static paths use an exact-match dict, dynamic patterns are precompiled
URLPattern regexes scanned in registration order. Static always wins
over dynamic, regardless of registration order.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any

from .urlpattern import compile_pathname

if TYPE_CHECKING:
    from collections.abc import Callable

# Routing key for WebSocket routes. Lowercase on purpose: incoming HTTP
# methods are upper-cased, so this can never collide with one.
WEBSOCKET_METHOD = "#websocket"


class Route:
    __slots__ = ("handler", "method", "middleware", "pattern")

    def __init__(
        self,
        method: str,
        pattern: str,
        handler: Callable[..., Any],
        middleware: tuple[Any, ...] = (),
    ) -> None:
        self.method = method
        self.pattern = pattern
        self.handler = handler
        self.middleware = middleware

    def __repr__(self) -> str:
        return f"Route({self.method} {self.pattern!r})"


class Router:
    __slots__ = ("_dynamic", "_static")

    def __init__(self) -> None:
        self._static: dict[str, dict[str, Route]] = {}
        self._dynamic: list[tuple[str, re.Pattern[str], tuple[str, ...], Route]] = []

    def add(self, route: Route) -> None:
        static, regex, names = compile_pathname(route.pattern)
        if static is not None:
            methods = self._static.setdefault(static, {})
            if route.method in methods:
                raise ValueError(f"duplicate route: {route.method} {route.pattern}")
            methods[route.method] = route
            return
        if regex is None:  # pragma: no cover - compile_pathname guarantees one of the two
            raise AssertionError("dynamic pattern compiled to neither static nor regex")
        for method, _, _, existing in self._dynamic:
            if method == route.method and existing.pattern == route.pattern:
                raise ValueError(f"duplicate route: {route.method} {route.pattern}")
        self._dynamic.append((route.method, regex, names, route))

    def match(self, method: str, path: str) -> tuple[Route, dict[str, str | None]] | None:
        methods = self._static.get(path)
        if methods is not None and method in methods:
            return methods[method], {}
        for m, regex, names, route in self._dynamic:
            if m != method:
                continue
            matched = regex.match(path)
            if matched is not None:
                return route, dict(zip(names, matched.groups(), strict=True))
        return None

    def allowed_methods(self, path: str) -> list[str]:
        """Methods that would match this path — feeds 405 ``Allow`` headers."""
        methods: set[str] = set()
        static = self._static.get(path)
        if static:
            methods.update(m for m in static if m != WEBSOCKET_METHOD)
        for method, regex, _, _ in self._dynamic:
            if method != WEBSOCKET_METHOD and method not in methods and regex.match(path):
                methods.add(method)
        if "GET" in methods:
            methods.add("HEAD")
        return sorted(methods)
