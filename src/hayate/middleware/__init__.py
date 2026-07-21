"""Built-in middleware. All zero-dependency; each is a factory returning
an ``async def middleware(c, next)``.
"""

from .basic_auth import basic_auth
from .body_limit import body_limit
from .compress import compress
from .cors import cors
from .etag import etag
from .logger import logger
from .secure_headers import secure_headers
from .timeout import timeout

__all__ = [
    "basic_auth",
    "body_limit",
    "compress",
    "cors",
    "etag",
    "logger",
    "secure_headers",
    "timeout",
]
