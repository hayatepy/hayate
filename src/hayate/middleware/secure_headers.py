"""Security response headers (CSP, HSTS, and friends).

Values are assembled once at construction time (startup-time work is
free — DESIGN.md §14.1); existing response headers are never overridden.
"""

from __future__ import annotations

from ..context import Context, Middleware, Next


def secure_headers(
    *,
    content_security_policy: str | None = None,
    strict_transport_security: str | None = "max-age=31536000; includeSubDomains",
    x_content_type_options: str | None = "nosniff",
    x_frame_options: str | None = "SAMEORIGIN",
    referrer_policy: str | None = "no-referrer",
    permissions_policy: str | None = None,
) -> Middleware:
    pairs = [
        (name, value)
        for name, value in (
            ("content-security-policy", content_security_policy),
            ("strict-transport-security", strict_transport_security),
            ("x-content-type-options", x_content_type_options),
            ("x-frame-options", x_frame_options),
            ("referrer-policy", referrer_policy),
            ("permissions-policy", permissions_policy),
        )
        if value is not None
    ]

    async def secure_headers_middleware(c: Context, next_: Next) -> None:
        await next_()
        res = c.res
        if res is None:
            return
        for name, value in pairs:
            if not res.headers.has(name):
                res.headers.set(name, value)

    return secure_headers_middleware
