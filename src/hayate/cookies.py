"""Cookies (RFC 6265bis): parsing, ``Set-Cookie`` serialization, and
HMAC-SHA256 value signing.

Serialization enforces the spec's invariants: ``__Host-`` names require
``Secure``, ``Path=/`` and no ``Domain``; ``__Secure-`` names require
``Secure``; ``SameSite=None`` requires ``Secure``.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import re

_NAME_RE = re.compile(r"^[!#$%&'*+\-.^_`|~0-9A-Za-z]+$")
_BAD_VALUE_RE = re.compile(r'[\x00-\x1f\x7f",;\\ ]')
_SAME_SITE = ("Strict", "Lax", "None")


def parse_cookies(header: str) -> dict[str, str]:
    """Parse a ``Cookie`` request header. First occurrence wins."""
    cookies: dict[str, str] = {}
    for part in header.split(";"):
        name, _, value = part.strip().partition("=")
        if name:
            cookies.setdefault(name, value)
    return cookies


def serialize_set_cookie(
    name: str,
    value: str,
    *,
    max_age: int | None = None,
    expires: str | None = None,
    path: str | None = "/",
    domain: str | None = None,
    secure: bool = False,
    http_only: bool = False,
    same_site: str | None = None,
) -> str:
    if not _NAME_RE.match(name):
        raise ValueError(f"invalid cookie name: {name!r}")
    if _BAD_VALUE_RE.search(value):
        raise ValueError(f"invalid cookie value for {name!r} (encode it first)")
    if same_site is not None:
        same_site = same_site.capitalize()
        if same_site not in _SAME_SITE:
            raise ValueError(f"same_site must be one of {_SAME_SITE}")
        if same_site == "None" and not secure:
            raise ValueError("SameSite=None requires secure=True")
    if name.startswith("__Host-") and not (secure and path == "/" and domain is None):
        raise ValueError("__Host- cookies require secure=True, path='/', and no domain")
    if name.startswith("__Secure-") and not secure:
        raise ValueError("__Secure- cookies require secure=True")

    parts = [f"{name}={value}"]
    if max_age is not None:
        parts.append(f"Max-Age={int(max_age)}")
    if expires is not None:
        parts.append(f"Expires={expires}")
    if domain is not None:
        parts.append(f"Domain={domain}")
    if path is not None:
        parts.append(f"Path={path}")
    if secure:
        parts.append("Secure")
    if http_only:
        parts.append("HttpOnly")
    if same_site is not None:
        parts.append(f"SameSite={same_site}")
    return "; ".join(parts)


def sign_value(value: str, secret: str | bytes) -> str:
    """Append an HMAC-SHA256 signature: ``value.base64url(sig)``."""
    key = secret.encode("utf-8") if isinstance(secret, str) else secret
    signature = hmac.new(key, value.encode("utf-8"), hashlib.sha256).digest()
    encoded = base64.urlsafe_b64encode(signature).rstrip(b"=").decode("ascii")
    return f"{value}.{encoded}"


def unsign_value(signed: str, secret: str | bytes) -> str | None:
    """Verify a signed value; returns the value, or None if tampered."""
    value, separator, _ = signed.rpartition(".")
    if not separator:
        return None
    expected = sign_value(value, secret)
    return value if hmac.compare_digest(expected, signed) else None
