"""WHATWG-style ``URL`` and ``URLSearchParams`` (practical subset).

Implements the URL Standard's component model and
``application/x-www-form-urlencoded`` parsing/serialization.

Documented subset for v0.1 (conformance is measured, not assumed —
see DESIGN.md §13.2):

- Only URLs with an authority (``scheme://host/...``) are supported.
- No IDNA/punycode processing; hostnames are lowercased as-is.
- Percent-encoding in paths is preserved, not re-normalized.
- ``URL`` is read-only; component setters may come later.
- ``url.search_params`` is a parsed snapshot; mutating it does not write
  back into the URL.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Iterator, Mapping
from urllib.parse import unquote

_SCHEME_CHARS = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789+-."
_DEFAULT_PORTS = {"http": "80", "https": "443", "ws": "80", "wss": "443", "ftp": "21"}
_SPECIAL_SCHEMES = frozenset(_DEFAULT_PORTS) | {"file"}

# application/x-www-form-urlencoded byte serializer safe set (URL Standard).
_FORM_SAFE = frozenset(b"abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789*-._")

# C0 controls and space — trimmed from both ends per the URL Standard.
_C0_AND_SPACE = "".join(chr(i) for i in range(0x21))

# Component percent-encode sets (URL Standard). "%" is never re-encoded,
# so existing percent-escapes pass through untouched.
_FRAGMENT_ENCODE = frozenset(' "<>`')
_QUERY_ENCODE = frozenset(' "#<>')
_QUERY_ENCODE_SPECIAL = _QUERY_ENCODE | {"'"}
_PATH_ENCODE = _QUERY_ENCODE | frozenset("?`{}")
_USERINFO_ENCODE = _PATH_ENCODE | frozenset("/:;=@[\\]^|")
_FORBIDDEN_HOST_CHARS = frozenset("\x00\t\n\r #/:<>?@[\\]^|")


# Per-set "does this string need any encoding?" probes — the common case
# (already-encoded ASCII) short-circuits without a Python-level loop.
_NEEDS_ENCODE = {
    encode_set: re.compile(
        "[" + re.escape("".join(sorted(encode_set))) + "\\x00-\\x1f\\x7f]|[^\\x00-\\x7f]"
    )
    for encode_set in (
        _FRAGMENT_ENCODE,
        _QUERY_ENCODE,
        _QUERY_ENCODE_SPECIAL,
        _PATH_ENCODE,
        _USERINFO_ENCODE,
    )
}

_FORBIDDEN_HOST_RE = re.compile(r"[\x00-\x1f\x7f #/:<>?@\[\\\]^|]")


def _encode_component(value: str, encode_set: frozenset[str]) -> str:
    if not value or _NEEDS_ENCODE[encode_set].search(value) is None:
        return value
    out: list[str] = []
    for ch in value:
        code = ord(ch)
        if 0x20 <= code <= 0x7E and ch not in encode_set:
            out.append(ch)
        else:
            out.extend(f"%{byte:02X}" for byte in ch.encode("utf-8"))
    return "".join(out)


def _preprocess(url: str) -> str:
    """URL Standard input preprocessing: trim C0/space, drop tab/newline."""
    url = url.strip(_C0_AND_SPACE)
    return url.replace("\t", "").replace("\n", "").replace("\r", "")


def _split_scheme(url: str) -> tuple[str, str] | None:
    """Return (scheme, rest) if the string starts with a URL scheme."""
    if not url or not url[0].isascii() or not url[0].isalpha():
        return None
    for i, ch in enumerate(url):
        if ch == ":":
            return url[:i].lower(), url[i + 1 :]
        if ch not in _SCHEME_CHARS:
            return None
    return None


def form_urlencode(value: str) -> str:
    out: list[str] = []
    for byte in value.encode("utf-8"):
        if byte == 0x20:
            out.append("+")
        elif byte in _FORM_SAFE:
            out.append(chr(byte))
        else:
            out.append(f"%{byte:02X}")
    return "".join(out)


def form_urldecode(value: str) -> str:
    return unquote(value.replace("+", " "), errors="replace")


def parse_form_urlencoded(query: str) -> list[tuple[str, str]]:
    pairs: list[tuple[str, str]] = []
    for part in query.split("&"):
        if not part:
            continue
        name, _, value = part.partition("=")
        pairs.append((form_urldecode(name), form_urldecode(value)))
    return pairs


# Dot segments compare after percent-decoding just the dots, ASCII
# case-insensitively (WHATWG path state): "%2e" == ".".
_SINGLE_DOTS = frozenset((".", "%2e"))
_DOUBLE_DOTS = frozenset(("..", ".%2e", "%2e.", "%2e%2e"))


def _remove_dot_segments(path: str) -> str:
    output: list[str] = []
    segments = path.split("/")
    last = len(segments) - 1
    for i in range(1, last + 1):
        segment = segments[i]
        low = segment.lower() if "%" in segment else segment
        if low in _DOUBLE_DOTS:
            if output:
                output.pop()
            if i == last:
                output.append("")
        elif low in _SINGLE_DOTS:
            if i == last:
                output.append("")
        else:
            output.append(segment)
    return "/" + "/".join(output)


def _needs_dot_removal(path: str) -> bool:
    return "/." in path or ("%2" in path and "%2e" in path.lower())


def _parse_ipv4_number(part: str) -> int | None:
    """WHATWG IPv4-number parser: decimal, ``0x`` hex, or ``0``-octal."""
    if not part:
        return None
    radix = 10
    if len(part) >= 2 and part[0] == "0" and part[1] in "xX":
        part = part[2:]
        radix = 16
    elif len(part) >= 2 and part[0] == "0":
        part = part[1:]
        radix = 8
    if not part:
        return 0
    digits = "0123456789abcdef"[:radix]
    low = part.lower()
    if any(ch not in digits for ch in low):
        return None
    return int(low, radix)


def _ends_in_number(hostname: str) -> bool:
    """WHATWG ends-in-a-number checker: such hosts must parse as IPv4."""
    parts = hostname.split(".")
    if parts[-1] == "":
        if len(parts) == 1:
            return False
        parts = parts[:-1]
    tail = parts[-1]
    if tail and all(ch in "0123456789" for ch in tail):
        return True
    return _parse_ipv4_number(tail) is not None


def _canonicalize_ipv4(hostname: str, url: str) -> str:
    """WHATWG IPv4 parser: canonical dotted-decimal, or ``ValueError``."""
    parts = hostname.split(".")
    if parts[-1] == "":
        parts = parts[:-1]
    if not parts or len(parts) > 4:
        raise ValueError(f"invalid IPv4 host in URL: {url!r}")
    numbers: list[int] = []
    for part in parts:
        value = _parse_ipv4_number(part)
        if value is None:
            raise ValueError(f"invalid IPv4 host in URL: {url!r}")
        numbers.append(value)
    if any(n > 255 for n in numbers[:-1]) or numbers[-1] >= 256 ** (5 - len(numbers)):
        raise ValueError(f"IPv4 address out of range in URL: {url!r}")
    address = numbers[-1]
    for i, n in enumerate(numbers[:-1]):
        address += n << (8 * (3 - i))
    return ".".join(str((address >> (8 * (3 - i))) & 0xFF) for i in range(4))


def _canonicalize_ipv6(inner: str, url: str) -> str:
    """WHATWG IPv6 parser + serializer (RFC 5952 ``::`` compression)."""

    def fail() -> ValueError:
        return ValueError(f"invalid IPv6 host in URL: {url!r}")

    pieces = [0] * 8
    piece_index = 0
    compress: int | None = None
    pointer = 0
    n = len(inner)
    if pointer < n and inner[pointer] == ":":
        if not inner.startswith("::"):
            raise fail()
        pointer += 2
        piece_index += 1
        compress = piece_index
    while pointer < n:
        if piece_index == 8:
            raise fail()
        if inner[pointer] == ":":
            if compress is not None:
                raise fail()
            pointer += 1
            piece_index += 1
            compress = piece_index
            continue
        value = length = 0
        while length < 4 and pointer < n and inner[pointer] in "0123456789abcdefABCDEF":
            value = value * 16 + int(inner[pointer], 16)
            pointer += 1
            length += 1
        if pointer < n and inner[pointer] == ".":
            if length == 0:
                raise fail()
            pointer -= length
            if piece_index > 6:
                raise fail()
            numbers_seen = 0
            while pointer < n:
                ipv4_piece: int | None = None
                if numbers_seen > 0:
                    if inner[pointer] == "." and numbers_seen < 4:
                        pointer += 1
                    else:
                        raise fail()
                if pointer >= n or inner[pointer] not in "0123456789":
                    raise fail()
                while pointer < n and inner[pointer] in "0123456789":
                    digit = int(inner[pointer])
                    if ipv4_piece is None:
                        ipv4_piece = digit
                    elif ipv4_piece == 0:
                        raise fail()
                    else:
                        ipv4_piece = ipv4_piece * 10 + digit
                    if ipv4_piece > 255:
                        raise fail()
                    pointer += 1
                pieces[piece_index] = pieces[piece_index] * 256 + (ipv4_piece or 0)
                numbers_seen += 1
                if numbers_seen in (2, 4):
                    piece_index += 1
            if numbers_seen != 4:
                raise fail()
            break
        if pointer < n:
            if inner[pointer] != ":":
                raise fail()
            pointer += 1
            if pointer == n:
                raise fail()
        pieces[piece_index] = value
        piece_index += 1
    if compress is not None:
        swaps = piece_index - compress
        piece_index = 7
        while piece_index != 0 and swaps > 0:
            other = compress + swaps - 1
            pieces[piece_index], pieces[other] = pieces[other], pieces[piece_index]
            piece_index -= 1
            swaps -= 1
    elif piece_index != 8:
        raise fail()
    # Serialize: compress the leftmost longest run (>= 2) of zero pieces.
    best_start, best_len = -1, 1
    i = 0
    while i < 8:
        if pieces[i] == 0:
            j = i
            while j < 8 and pieces[j] == 0:
                j += 1
            if j - i > best_len:
                best_start, best_len = i, j - i
            i = j
        else:
            i += 1
    parts: list[str] = []
    i = 0
    while i < 8:
        if i == best_start:
            if i == 0:
                parts.append("")
            parts.append("")
            i += best_len
            if i == 8:
                parts.append("")
            continue
        parts.append(format(pieces[i], "x"))
        i += 1
    return ":".join(parts)


class URLSearchParams:
    """WHATWG ``URLSearchParams`` over the query string."""

    __slots__ = ("_pairs",)

    def __init__(
        self,
        init: URLSearchParams | str | Mapping[str, str] | Iterable[tuple[str, str]] | None = None,
    ) -> None:
        if isinstance(init, URLSearchParams):
            self._pairs: list[tuple[str, str]] = list(init._pairs)
        elif isinstance(init, str):
            self._pairs = parse_form_urlencoded(init.removeprefix("?"))
        elif isinstance(init, Mapping):
            self._pairs = [(str(k), str(v)) for k, v in init.items()]
        elif init is None:
            self._pairs = []
        else:
            self._pairs = [(str(k), str(v)) for k, v in init]

    def get(self, name: str) -> str | None:
        for n, v in self._pairs:
            if n == name:
                return v
        return None

    def get_all(self, name: str) -> list[str]:
        return [v for n, v in self._pairs if n == name]

    def has(self, name: str, value: str | None = None) -> bool:
        return any(n == name and (value is None or v == value) for n, v in self._pairs)

    def append(self, name: str, value: str) -> None:
        self._pairs.append((name, value))

    def set(self, name: str, value: str) -> None:
        out: list[tuple[str, str]] = []
        replaced = False
        for n, v in self._pairs:
            if n == name:
                if not replaced:
                    out.append((name, value))
                    replaced = True
            else:
                out.append((n, v))
        if not replaced:
            out.append((name, value))
        self._pairs = out

    def delete(self, name: str, value: str | None = None) -> None:
        self._pairs = [
            (n, v) for n, v in self._pairs if n != name or (value is not None and v != value)
        ]

    def sort(self) -> None:
        self._pairs.sort(key=lambda pair: pair[0])

    def __iter__(self) -> Iterator[tuple[str, str]]:
        return iter(list(self._pairs))

    def __len__(self) -> int:
        return len(self._pairs)

    def __str__(self) -> str:
        return "&".join(f"{form_urlencode(n)}={form_urlencode(v)}" for n, v in self._pairs)

    def __repr__(self) -> str:
        return f"URLSearchParams({str(self)!r})"


class URL:
    """WHATWG ``URL`` — the documented subset measured in docs/conformance.md."""

    __slots__ = (
        "_hash",
        "_hostname",
        "_params",
        "_password",
        "_pathname",
        "_port",
        "_scheme",
        "_search",
        "_username",
    )

    def __init__(self, url: str, base: str | URL | None = None) -> None:
        url = _preprocess(url)
        if _split_scheme(url) is None:
            if base is None:
                raise ValueError(f"invalid URL (no scheme and no base): {url!r}")
            base_url = base if isinstance(base, URL) else URL(base)
            url = _resolve(url, base_url)
        self._params: URLSearchParams | None = None
        self._parse(url)

    @classmethod
    def _from_server(cls, scheme: str, host: str, path: str, query: str) -> URL:
        """Adapter fast path: trusted, already-encoded components.

        Servers hand adapters pre-validated, wire-encoded values, so the
        full parser (validation, percent-encoding) is skipped. Only
        host:port splitting, default-port elision, and dot-segment
        removal (when present) are performed.
        """
        url = cls.__new__(cls)
        url._params = None
        url._scheme = scheme
        url._username = ""
        url._password = ""
        if host.startswith("["):
            close = host.find("]")
            url._hostname = host[: close + 1].lower() if close != -1 else host.lower()
            rest = host[close + 1 :] if close != -1 else ""
            port = rest[1:] if rest.startswith(":") else ""
        else:
            hostname, _, port = host.partition(":")
            url._hostname = hostname.lower()
        if port and _DEFAULT_PORTS.get(scheme) == port:
            port = ""
        url._port = port
        if not path:
            path = "/"
        elif _needs_dot_removal(path):
            path = _remove_dot_segments(path)
        url._pathname = path
        url._search = f"?{query}" if query else ""
        url._hash = ""
        return url

    def _parse(self, url: str) -> None:
        split = _split_scheme(url)
        if split is None:
            raise ValueError(f"invalid URL: {url!r}")
        scheme, rest = split
        is_special = scheme in _DEFAULT_PORTS
        if is_special:
            # Special schemes tolerate any number of "/" or "\" after the
            # colon (URL Standard "special authority slashes" state).
            rest = rest.lstrip("/\\")
        elif rest.startswith("//"):
            rest = rest[2:]
        else:
            raise ValueError(f"unsupported URL (no authority): {url!r}")

        terminators = "/?#\\" if is_special else "/?#"
        end = len(rest)
        for ch in terminators:
            pos = rest.find(ch)
            if pos != -1:
                end = min(end, pos)
        authority, remainder = rest[:end], rest[end:]

        username = password = ""
        if "@" in authority:
            userinfo, hostport = authority.rsplit("@", 1)
            raw_username, _, raw_password = userinfo.partition(":")
            username = _encode_component(raw_username, _USERINFO_ENCODE)
            password = _encode_component(raw_password, _USERINFO_ENCODE)
        else:
            hostport = authority

        if hostport.startswith("["):
            close = hostport.find("]")
            if close == -1:
                raise ValueError(f"invalid IPv6 host in URL: {url!r}")
            hostname = "[" + _canonicalize_ipv6(hostport[1:close], url) + "]"
            portpart = hostport[close + 1 :]
            if portpart and not portpart.startswith(":"):
                raise ValueError(f"invalid host in URL: {url!r}")
            port = portpart[1:] if portpart else ""
        else:
            hostname, _, port = hostport.partition(":")
            hostname = hostname.lower()
            if not hostname.isascii():
                # Silent mojibake would be worse than an explicit error.
                # The rejection doubles as the demand meter for IDNA:
                # the linked issue collects real use cases (DESIGN §14.4).
                raise ValueError(
                    f"non-ASCII host (IDNA not implemented — "
                    f"needed? comment at hayatepy/hayate#2): {url!r}"
                )
            if _FORBIDDEN_HOST_RE.search(hostname):
                raise ValueError(f"forbidden host code point in URL: {url!r}")
            if _ends_in_number(hostname):
                # WHATWG: a host whose last label is numeric *is* an IPv4
                # address — canonicalize or reject (overflow, bad digits).
                hostname = _canonicalize_ipv4(hostname, url)
        if not hostname:
            raise ValueError(f"empty host in URL: {url!r}")
        if port:
            if not port.isdigit():
                raise ValueError(f"invalid port in URL: {url!r}")
            number = int(port)
            if number > 65535:
                raise ValueError(f"port out of range in URL: {url!r}")
            port = str(number)
            if _DEFAULT_PORTS.get(scheme) == port:
                port = ""

        path = remainder
        fragment = ""
        pos = path.find("#")
        if pos != -1:
            fragment = path[pos:]
            path = path[:pos]
        search = ""
        pos = path.find("?")
        if pos != -1:
            search = path[pos:]
            path = path[:pos]
        if search == "?":
            search = ""
        elif search:
            query_set = _QUERY_ENCODE_SPECIAL if is_special else _QUERY_ENCODE
            search = "?" + _encode_component(search[1:], query_set)
        if fragment and fragment != "#":
            fragment = "#" + _encode_component(fragment[1:], _FRAGMENT_ENCODE)
        if is_special:
            path = path.replace("\\", "/")
        path = _encode_component(path, _PATH_ENCODE)
        if not path:
            path = "/"
        elif not path.startswith("/"):
            path = "/" + path

        self._scheme = scheme
        self._username = username
        self._password = password
        self._hostname = hostname
        self._port = port
        self._pathname = _remove_dot_segments(path)
        self._search = search
        self._hash = fragment if fragment != "#" else ""

    # -- components (URL Standard names, snake_case spelling) --------------

    @property
    def protocol(self) -> str:
        return self._scheme + ":"

    @property
    def username(self) -> str:
        return self._username

    @property
    def password(self) -> str:
        return self._password

    @property
    def hostname(self) -> str:
        return self._hostname

    @property
    def port(self) -> str:
        return self._port

    @property
    def host(self) -> str:
        return f"{self._hostname}:{self._port}" if self._port else self._hostname

    @property
    def origin(self) -> str:
        if self._scheme in _SPECIAL_SCHEMES and self._scheme != "file":
            return f"{self._scheme}://{self.host}"
        return "null"

    @property
    def pathname(self) -> str:
        return self._pathname

    @property
    def search(self) -> str:
        return self._search

    @property
    def search_params(self) -> URLSearchParams:
        if self._params is None:
            self._params = URLSearchParams(self._search)
        return self._params

    @property
    def hash(self) -> str:
        return self._hash

    @property
    def href(self) -> str:
        userinfo = ""
        if self._username or self._password:
            userinfo = self._username
            if self._password:
                userinfo += f":{self._password}"
            userinfo += "@"
        return f"{self._scheme}://{userinfo}{self.host}{self._pathname}{self._search}{self._hash}"

    def __str__(self) -> str:
        return self.href

    def __repr__(self) -> str:
        return f"URL({self.href!r})"

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, URL):
            return NotImplemented
        return self.href == other.href

    def __hash__(self) -> int:
        return hash(self.href)


def _resolve(url: str, base: URL) -> str:
    """Resolve a relative reference against a base URL (pragmatic subset)."""
    if url == "":
        return base.href
    if url.startswith("//"):
        return base.protocol + url
    origin = f"{base.protocol}//{base.host}"
    if url.startswith("/"):
        return origin + url
    if url.startswith("?"):
        return origin + base.pathname + url
    if url.startswith("#"):
        return origin + base.pathname + base.search + url
    directory = base.pathname.rsplit("/", 1)[0]
    return f"{origin}{directory}/{url}"
