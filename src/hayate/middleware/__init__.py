"""Built-in middleware. All zero-dependency; each is a factory returning
an ``async def middleware(c, next)``.
"""

from .basic_auth import basic_auth
from .compress import compress
from .cors import cors
from .etag import etag
from .logger import logger

__all__ = ["basic_auth", "compress", "cors", "etag", "logger"]
