"""``URLPattern`` (WHATWG URL Pattern Standard) — pathname subset for routing.

v0.1 implements the documented subset used by the router:

- literal text, with ``\\`` escapes
- ``:name`` named segment groups (``[^/]+``)
- ``:name(regexp)`` and anonymous ``(regexp)`` matchers (capturing
  groups are rejected; regexps are interpreted by Python's ``re``, so
  JS-only syntax such as v-mode set operations is not supported)
- the ``?`` (optional) modifier on groups
- ``*`` full wildcards, exposed as numbered groups ("0", "1", ...)

Per the standard, a ``/`` immediately preceding a group is treated as the
group's prefix, so ``/books/:id?`` also matches ``/books``.

Unsupported syntax raises ``ValueError``: ``{}`` grouping and the ``+`` /
``*`` modifiers on named groups. Only the pathname component is modeled.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

_NAME_RE = re.compile(r"[A-Za-z0-9_$]+")
_SYNTAX_CHARS = frozenset(":*\\{}(")


@dataclass(frozen=True, slots=True)
class URLPatternComponentResult:
    """Match result for one URL component (only pathname in v0.1)."""

    input: str
    groups: dict[str, str | None]


@dataclass(frozen=True, slots=True)
class URLPatternResult:
    pathname: URLPatternComponentResult


def _has_capturing_group(regex: str) -> bool:
    i = 0
    while i < len(regex):
        ch = regex[i]
        if ch == "\\":
            i += 2
            continue
        if ch == "(" and not regex.startswith("(?", i):
            return True
        i += 1
    return False


def compile_pathname(
    pattern: str,
) -> tuple[str | None, re.Pattern[str] | None, tuple[str, ...]]:
    """Compile a pathname pattern.

    Returns ``(static_path, regex, group_names)``. ``static_path`` is set
    (and the other two empty) when the pattern contains no pattern syntax,
    letting callers use exact-match lookups.
    """
    if not _SYNTAX_CHARS.intersection(pattern):
        return pattern, None, ()

    out: list[str] = []
    names: list[str] = []
    literal: list[str] = []
    wildcard_count = 0
    i = 0

    def flush_literal() -> None:
        if literal:
            out.append(re.escape("".join(literal)))
            literal.clear()

    def take_prefix() -> str:
        if literal and literal[-1] == "/":
            literal.pop()
            return "/"
        return ""

    def read_regexp(start: int) -> tuple[str, int]:
        """Read a parenthesized regexp body; ``start`` points at '('."""
        depth = 1
        k = start + 1
        while k < len(pattern) and depth:
            if pattern[k] == "\\":
                k += 2
                continue
            if pattern[k] == "(":
                depth += 1
            elif pattern[k] == ")":
                depth -= 1
            k += 1
        if depth:
            raise ValueError(f"unbalanced '(' in pattern: {pattern!r}")
        body = pattern[start + 1 : k - 1]
        if not body:
            raise ValueError(f"empty regexp group in pattern: {pattern!r}")
        if not body.isascii():
            # The spec restricts regexp groups to ASCII.
            raise ValueError(f"non-ASCII regexp group in pattern: {pattern!r}")
        if _has_capturing_group(body):
            raise ValueError("capturing groups are not allowed in patterns; use (?:...)")
        return body, k

    def read_modifier(position: int) -> tuple[str, int]:
        if position < len(pattern) and pattern[position] in "?+*":
            modifier = pattern[position]
            if modifier in ("+", "*"):
                raise ValueError(
                    f"modifier {modifier!r} is not supported in the v0.1 pattern subset"
                )
            return modifier, position + 1
        return "", position

    def next_wildcard_name() -> str:
        nonlocal wildcard_count
        name = str(wildcard_count)
        if name in names:
            raise ValueError(f"duplicate group name {name!r} in pattern: {pattern!r}")
        wildcard_count += 1
        return name

    def emit_group(name: str, body: str, modifier: str) -> None:
        prefix = take_prefix()
        flush_literal()
        names.append(name)
        if modifier == "?":
            out.append(f"(?:{re.escape(prefix)}({body}))?")
        else:
            out.append(f"{re.escape(prefix)}({body})")

    while i < len(pattern):
        ch = pattern[i]
        if ch == "\\":
            if i + 1 >= len(pattern):
                raise ValueError(f"dangling escape in pattern: {pattern!r}")
            literal.append(pattern[i + 1])
            i += 2
        elif ch in "{}":
            raise ValueError("'{}' groups are not supported in the v0.1 pattern subset")
        elif ch == ":":
            m = _NAME_RE.match(pattern, i + 1)
            if m is None:
                raise ValueError(f"missing group name at index {i} in pattern: {pattern!r}")
            name = m.group(0)
            if name in names:
                raise ValueError(f"duplicate group name {name!r} in pattern: {pattern!r}")
            j = m.end()
            body = "[^/]+"
            if j < len(pattern) and pattern[j] == "(":
                body, j = read_regexp(j)
            modifier, j = read_modifier(j)
            emit_group(name, body, modifier)
            i = j
        elif ch == "(":
            # Anonymous regexp group — numbered like wildcards, per the spec.
            body, j = read_regexp(i)
            modifier, j = read_modifier(j)
            emit_group(next_wildcard_name(), body, modifier)
            i = j
        elif ch == "*":
            modifier, j = read_modifier(i + 1)
            if modifier:
                raise ValueError(
                    "modifiers on '*' wildcards are not supported in the v0.1 pattern subset"
                )
            emit_group(next_wildcard_name(), ".*", "")
            i = j
        else:
            literal.append(ch)
            i += 1

    flush_literal()
    try:
        return None, re.compile("^" + "".join(out) + "$"), tuple(names)
    except re.error as exc:
        raise ValueError(f"invalid regexp in pattern {pattern!r}: {exc}") from exc


class URLPattern:
    """Pattern matcher for URL pathnames (subset of the URLPattern standard)."""

    __slots__ = ("_names", "_regex", "_static", "pathname")

    def __init__(self, pathname: str = "*") -> None:
        self.pathname = pathname
        self._static, self._regex, self._names = compile_pathname(pathname)

    def test(self, pathname: str) -> bool:
        if self._regex is None:
            return pathname == self._static
        return self._regex.match(pathname) is not None

    def exec(self, pathname: str) -> URLPatternResult | None:
        if self._regex is None:
            if pathname != self._static:
                return None
            groups: dict[str, str | None] = {}
        else:
            m = self._regex.match(pathname)
            if m is None:
                return None
            groups = dict(zip(self._names, m.groups(), strict=True))
        return URLPatternResult(pathname=URLPatternComponentResult(input=pathname, groups=groups))

    def __repr__(self) -> str:
        return f"URLPattern(pathname={self.pathname!r})"
