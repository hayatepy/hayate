"""Built-in middleware. All zero-dependency; each is a factory returning
an ``async def middleware(c, next)``.
"""

from .basic_auth import basic_auth
from .body_limit import body_limit
from .cache import cache
from .compress import compress
from .cors import cors
from .etag import etag
from .logger import logger
from .rate_limit import MemoryRateLimitStore, RateLimitStore, rate_limit
from .secure_headers import secure_headers
from .static_files import static_files
from .timeout import timeout

__all__ = [
    "MemoryRateLimitStore",
    "RateLimitStore",
    "basic_auth",
    "body_limit",
    "cache",
    "compress",
    "cors",
    "etag",
    "logger",
    "rate_limit",
    "secure_headers",
    "static_files",
    "timeout",
]
