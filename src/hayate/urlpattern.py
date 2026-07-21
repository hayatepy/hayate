"""``URLPattern`` (WHATWG URL Pattern Standard) — pathname subset for routing.

v0.1 implements the documented subset used by the router:

- literal text, with ``\\`` escapes
- ``:name`` named segment groups (``[^/]+``)
- ``:name(regex)`` custom matchers (capturing groups are rejected)
- the ``?`` (optional) modifier on named groups
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
                depth = 1
                k = j + 1
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
                body = pattern[j + 1 : k - 1]
                if not body:
                    raise ValueError(f"empty regex group in pattern: {pattern!r}")
                if _has_capturing_group(body):
                    raise ValueError("capturing groups are not allowed in patterns; use (?:...)")
                j = k
            modifier = ""
            if j < len(pattern) and pattern[j] in "?+*":
                modifier = pattern[j]
                j += 1
            if modifier in ("+", "*"):
                raise ValueError(
                    f"modifier {modifier!r} is not supported in the v0.1 pattern subset"
                )
            prefix = take_prefix()
            flush_literal()
            names.append(name)
            if modifier == "?":
                out.append(f"(?:{re.escape(prefix)}({body}))?")
            else:
                out.append(f"{re.escape(prefix)}({body})")
            i = j
        elif ch == "*":
            prefix = take_prefix()
            flush_literal()
            names.append(str(wildcard_count))
            wildcard_count += 1
            out.append(f"{re.escape(prefix)}(.*)")
            i += 1
        else:
            literal.append(ch)
            i += 1

    flush_literal()
    return None, re.compile("^" + "".join(out) + "$"), tuple(names)


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
