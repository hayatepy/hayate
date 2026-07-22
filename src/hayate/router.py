"""Method x pathname routing table.

Three tiers, in match order (scaling curves measured in DESIGN §14.4):

1. **static** — exact-match dict for patterns with no syntax.
2. **trie** — patterns made only of literal segments and whole-segment
   ``:name`` parameters walk a segment trie: O(path segments) whatever
   the route count (0.66 µs flat vs 76 µs for a 1024-route linear scan).
3. **regex** — everything else (regexp constraints, optional params,
   wildcards) stays as precompiled URLPattern regexes in a linear tail.

Static always wins. Between the trie and the regex tail, *registration
order* decides: every dynamic route carries its registration index and
the lowest matching index wins — exactly how the previous single linear
scan behaved, so tiering is invisible to applications.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any

from .urlpattern import _SYNTAX_CHARS, compile_pathname

if TYPE_CHECKING:
    from collections.abc import Callable

# Routing key for WebSocket routes. Lowercase on purpose: incoming HTTP
# methods are upper-cased, so this can never collide with one.
WEBSOCKET_METHOD = "#websocket"

# Never mutated — handed out for every parameterless match.
_NO_PARAMS: dict[str, str | None] = {}

# Trie keys for children-by-parameter and leaf entries. Object identity
# means no path segment string can ever collide with them.
_PARAM: Any = object()
_LEAF: Any = object()

_PLAIN_PARAM_RE = re.compile(r"^:[A-Za-z_][A-Za-z0-9_]*$")


def _plain_segments(pattern: str) -> list[str] | None:
    """Segments for the trie tier, or None when the pattern needs regexes.

    Eligible patterns consist only of literal segments and whole-segment
    ``:name`` parameters — no regexp groups, no modifiers, no wildcards.
    """
    if not pattern.startswith("/"):
        return None
    segments = pattern.split("/")[1:]
    for segment in segments:
        if segment.startswith(":"):
            if not _PLAIN_PARAM_RE.match(segment):
                return None
        elif _SYNTAX_CHARS.intersection(segment):
            return None
    return segments


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
    __slots__ = ("_all", "_count", "_regex", "_static", "_trie")

    def __init__(self) -> None:
        self._static: dict[str, dict[str, Route]] = {}
        self._trie: dict[Any, Any] = {}
        self._regex: list[tuple[int, str, re.Pattern[str], tuple[str, ...], Route]] = []
        self._count = 0  # registration index shared by the dynamic tiers
        self._all: list[Route] = []  # registration order, for introspection

    def add(self, route: Route) -> None:
        static, regex, names = compile_pathname(route.pattern)
        if static is not None:
            methods = self._static.setdefault(static, {})
            if route.method in methods:
                raise ValueError(f"duplicate route: {route.method} {route.pattern}")
            methods[route.method] = route
            self._all.append(route)
            return
        if regex is None:  # pragma: no cover - compile_pathname guarantees one of the two
            raise AssertionError("dynamic pattern compiled to neither static nor regex")
        index = self._count
        self._count += 1
        segments = _plain_segments(route.pattern)
        if segments is not None:
            self._trie_add(segments, route, index)
            self._all.append(route)
            return
        for _, method, _, _, existing in self._regex:
            if method == route.method and existing.pattern == route.pattern:
                raise ValueError(f"duplicate route: {route.method} {route.pattern}")
        self._regex.append((index, route.method, regex, names, route))
        self._all.append(route)

    def _trie_add(self, segments: list[str], route: Route, index: int) -> None:
        node = self._trie
        names: list[str] = []
        for segment in segments:
            if segment.startswith(":"):
                names.append(segment[1:])
                node = node.setdefault(_PARAM, {})
            else:
                node = node.setdefault(segment, {})
        leaf = node.setdefault(_LEAF, {})
        entry = leaf.get(route.method)
        if entry is not None:
            if entry[0].pattern == route.pattern:
                raise ValueError(f"duplicate route: {route.method} {route.pattern}")
            return  # same-shape pattern: the earlier registration keeps winning
        leaf[route.method] = (route, tuple(names), index)

    def match(self, method: str, path: str) -> tuple[Route, dict[str, str | None]] | None:
        methods = self._static.get(path)
        if methods is not None and method in methods:
            return methods[method], _NO_PARAMS
        best = self._trie_match(method, path) if self._trie and path.startswith("/") else None
        limit = best[0] if best is not None else None
        for index, m, regex, names, route in self._regex:
            if limit is not None and index > limit:
                break  # the tail is index-ordered; nothing later can win
            if m != method:
                continue
            matched = regex.match(path)
            if matched is not None:
                return route, dict(zip(names, matched.groups(), strict=True))
        if best is not None:
            _, route, names, values = best
            return route, dict(zip(names, values, strict=True))
        return None

    def _trie_match(
        self, method: str, path: str
    ) -> tuple[int, Route, tuple[str, ...], tuple[str, ...]] | None:
        segments = path.split("/")  # path starts with "/", so segments[0] == ""
        total = len(segments)
        best: tuple[int, Route, tuple[str, ...], tuple[str, ...]] | None = None
        # Greedy walk with lazy backtracking: branch points (a node where
        # both the literal and the parameter child could match) are rare,
        # so the stack is only materialized when one is met. Every matching
        # leaf is still visited — overlapping routes settle by registration
        # index, and a literal dead-end falls back to the parameter branch.
        stack: list[tuple[dict[Any, Any], int, tuple[str, ...]]] | None = None
        node = self._trie
        i = 1
        values: tuple[str, ...] = ()
        while True:
            if i == total:
                leaf = node.get(_LEAF)
                if leaf is not None:
                    entry = leaf.get(method)
                    if entry is not None and (best is None or entry[2] < best[0]):
                        route, names, index = entry
                        best = (index, route, names, values)
            else:
                segment = segments[i]
                child = node.get(segment)
                # Parameters match one non-empty segment, like [^/]+.
                param_child = node.get(_PARAM) if segment else None
                if child is not None:
                    if param_child is not None:
                        if stack is None:
                            stack = []
                        stack.append((param_child, i + 1, (*values, segment)))
                    node = child
                    i += 1
                    continue
                if param_child is not None:
                    values = (*values, segment)
                    node = param_child
                    i += 1
                    continue
            if not stack:
                return best
            node, i, values = stack.pop()

    def allowed_methods(self, path: str) -> list[str]:
        """Methods that would match this path — feeds 405 ``Allow`` headers."""
        methods: set[str] = set()
        static = self._static.get(path)
        if static:
            methods.update(m for m in static if m != WEBSOCKET_METHOD)
        if self._trie and path.startswith("/"):
            segments = path.split("/")[1:]
            stack: list[tuple[dict[Any, Any], int]] = [(self._trie, 0)]
            while stack:
                node, i = stack.pop()
                if i == len(segments):
                    leaf = node.get(_LEAF)
                    if leaf:
                        methods.update(m for m in leaf if m != WEBSOCKET_METHOD)
                    continue
                segment = segments[i]
                child = node.get(segment)
                if child is not None:
                    stack.append((child, i + 1))
                if segment:
                    param_child = node.get(_PARAM)
                    if param_child is not None:
                        stack.append((param_child, i + 1))
        for _, method, regex, _, _ in self._regex:
            if method != WEBSOCKET_METHOD and method not in methods and regex.match(path):
                methods.add(method)
        if "GET" in methods:
            methods.add("HEAD")
        return sorted(methods)
