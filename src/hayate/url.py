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

from collections.abc import Iterable, Iterator, Mapping
from urllib.parse import unquote

_SCHEME_CHARS = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789+-."
_DEFAULT_PORTS = {"http": "80", "https": "443", "ws": "80", "wss": "443", "ftp": "21"}
_SPECIAL_SCHEMES = frozenset(_DEFAULT_PORTS) | {"file"}

# application/x-www-form-urlencoded byte serializer safe set (URL Standard).
_FORM_SAFE = frozenset(b"abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789*-._")


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


def _remove_dot_segments(path: str) -> str:
    out: list[str] = []
    ends_with_slash = False
    for segment in path.split("/")[1:]:
        if segment == ".":
            ends_with_slash = True
            continue
        if segment == "..":
            if out:
                out.pop()
            ends_with_slash = True
            continue
        out.append(segment)
        ends_with_slash = False
    result = "/" + "/".join(out)
    if ends_with_slash and not result.endswith("/"):
        result += "/"
    return result


class URLSearchParams:
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
        if _split_scheme(url) is None:
            if base is None:
                raise ValueError(f"invalid URL (no scheme and no base): {url!r}")
            base_url = base if isinstance(base, URL) else URL(base)
            url = _resolve(url, base_url)
        self._params: URLSearchParams | None = None
        self._parse(url)

    def _parse(self, url: str) -> None:
        split = _split_scheme(url)
        if split is None:
            raise ValueError(f"invalid URL: {url!r}")
        scheme, rest = split
        if not rest.startswith("//"):
            raise ValueError(f"unsupported URL (no authority): {url!r}")
        rest = rest[2:]

        end = len(rest)
        for ch in "/?#":
            pos = rest.find(ch)
            if pos != -1:
                end = min(end, pos)
        authority, remainder = rest[:end], rest[end:]

        username = password = ""
        if "@" in authority:
            userinfo, hostport = authority.rsplit("@", 1)
            username, _, password = userinfo.partition(":")
        else:
            hostport = authority

        if hostport.startswith("["):
            close = hostport.find("]")
            if close == -1:
                raise ValueError(f"invalid IPv6 host in URL: {url!r}")
            hostname = hostport[: close + 1].lower()
            portpart = hostport[close + 1 :]
            if portpart and not portpart.startswith(":"):
                raise ValueError(f"invalid host in URL: {url!r}")
            port = portpart[1:] if portpart else ""
        else:
            hostname, _, port = hostport.partition(":")
            hostname = hostname.lower()
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
        if not path:
            path = "/"

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
