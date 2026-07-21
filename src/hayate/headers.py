"""Fetch-compatible ``Headers``.

Follows the WHATWG Fetch Standard semantics for header lists:
case-insensitive names, insertion order preserved, multiple values,
combined ``get()``, special-cased ``set-cookie``, and an immutability
guard. Names are stored lowercased (as they appear on the HTTP/2+ wire).

Naming policy: semantics from the standard, spelling per PEP 8
(``getSetCookie()`` -> ``set_cookie_list()``).
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Iterator, Mapping
from typing import Literal

_TOKEN_RE = re.compile(r"^[!#$%&'*+\-.^_`|~0-9A-Za-z]+$")
_BAD_VALUE_CHARS = ("\x00", "\r", "\n")


class Headers:
    __slots__ = ("_guard", "_pairs")

    def __init__(
        self,
        init: Headers | Mapping[str, str] | Iterable[tuple[str, str]] | None = None,
        *,
        guard: Literal["none", "immutable"] = "none",
    ) -> None:
        self._pairs: list[tuple[str, str]] = []
        self._guard: Literal["none", "immutable"] = "none"
        if isinstance(init, Headers):
            self._pairs.extend(init._pairs)
        elif isinstance(init, Mapping):
            for name, value in init.items():
                self.append(name, value)
        elif init is not None:
            for name, value in init:
                self.append(name, value)
        self._guard = guard

    @classmethod
    def _from_wire(
        cls,
        pairs: Iterable[tuple[str, str]],
        guard: Literal["none", "immutable"] = "none",
    ) -> Headers:
        """Adapter fast path: server-validated pairs, lowercased only."""
        headers = cls.__new__(cls)
        headers._pairs = [(name.lower(), value) for name, value in pairs]
        headers._guard = guard
        return headers

    def _append_trusted(self, name: str, value: str) -> None:
        """Framework-internal constants; skips validation on hot paths."""
        self._pairs.append((name, value))

    # -- validation -------------------------------------------------------

    def _check_mutable(self) -> None:
        if self._guard == "immutable":
            raise TypeError("headers are immutable")

    @staticmethod
    def _validate(name: str, value: str) -> tuple[str, str]:
        if not _TOKEN_RE.match(name):
            raise ValueError(f"invalid header name: {name!r}")
        # Normalize per Fetch: strip leading/trailing HTTP whitespace.
        value = value.strip(" \t")
        if any(ch in value for ch in _BAD_VALUE_CHARS):
            raise ValueError(f"invalid header value for {name!r}")
        try:
            value.encode("latin-1")
        except UnicodeEncodeError as exc:
            raise ValueError(f"header value for {name!r} is not latin-1 encodable") from exc
        return name.lower(), value

    # -- mutation ---------------------------------------------------------

    def append(self, name: str, value: str) -> None:
        self._check_mutable()
        lname, value = self._validate(name, value)
        self._pairs.append((lname, value))

    def set(self, name: str, value: str) -> None:
        """Replace the first occurrence, drop the rest (Fetch `set`)."""
        self._check_mutable()
        lname, value = self._validate(name, value)
        out: list[tuple[str, str]] = []
        replaced = False
        for n, v in self._pairs:
            if n == lname:
                if not replaced:
                    out.append((lname, value))
                    replaced = True
            else:
                out.append((n, v))
        if not replaced:
            out.append((lname, value))
        self._pairs = out

    def delete(self, name: str) -> None:
        self._check_mutable()
        lname = name.lower()
        self._pairs = [(n, v) for n, v in self._pairs if n != lname]

    # -- access -----------------------------------------------------------

    def get(self, name: str) -> str | None:
        """Combined value per Fetch: multiple values joined with ", "."""
        lname = name.lower()
        values = [v for n, v in self._pairs if n == lname]
        if not values:
            return None
        return ", ".join(values)

    def has(self, name: str) -> bool:
        lname = name.lower()
        return any(n == lname for n, _ in self._pairs)

    def set_cookie_list(self) -> list[str]:
        """All ``set-cookie`` values, uncombined (Fetch ``getSetCookie()``)."""
        return [v for n, v in self._pairs if n == "set-cookie"]

    def raw(self) -> list[tuple[str, str]]:
        """Underlying (name, value) pairs in insertion order, for adapters."""
        return list(self._pairs)

    # -- iteration (Fetch iterator: sorted, combined, set-cookie apart) ----

    def items(self) -> Iterator[tuple[str, str]]:
        for name in sorted({n for n, _ in self._pairs}):
            if name == "set-cookie":
                for value in self.set_cookie_list():
                    yield (name, value)
            else:
                yield (name, ", ".join(v for n, v in self._pairs if n == name))

    def keys(self) -> Iterator[str]:
        for name, _ in self.items():
            yield name

    def values(self) -> Iterator[str]:
        for _, value in self.items():
            yield value

    def __iter__(self) -> Iterator[tuple[str, str]]:
        return self.items()

    def __len__(self) -> int:
        return sum(1 for _ in self.items())

    def __contains__(self, name: object) -> bool:
        return isinstance(name, str) and self.has(name)

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Headers):
            return NotImplemented
        return sorted(self._pairs) == sorted(other._pairs)

    def __repr__(self) -> str:
        return f"Headers({self._pairs!r})"
