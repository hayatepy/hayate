"""HTTP Basic authentication (RFC 7617)."""

from __future__ import annotations

import base64
import binascii
import hmac

from ..context import Context, Middleware, Next
from ..exceptions import HTTPException


def basic_auth(*, username: str, password: str, realm: str = "Restricted") -> Middleware:
    """HTTP Basic Authentication (RFC 7617)."""

    expected_user = username.encode("utf-8")
    expected_password = password.encode("utf-8")

    async def basic_auth_middleware(c: Context, next_: Next) -> None:
        header = c.req.header("authorization")
        if header is not None and header[:6].lower() == "basic ":
            try:
                decoded = base64.b64decode(header[6:].strip(), validate=True).decode("utf-8")
            except (binascii.Error, UnicodeDecodeError):
                decoded = None
            if decoded is not None:
                given_user, _, given_password = decoded.partition(":")
                user_ok = hmac.compare_digest(given_user.encode("utf-8"), expected_user)
                password_ok = hmac.compare_digest(given_password.encode("utf-8"), expected_password)
                if user_ok and password_ok:
                    await next_()
                    return
        raise HTTPException(
            401,
            title="Unauthorized",
            headers={"www-authenticate": f'Basic realm="{realm}", charset="UTF-8"'},
        )

    return basic_auth_middleware
