"""Compact JSON serialization, with the optional Tier 2 accelerator.

The implementation is selected once at import time so call sites stay
monomorphic (DESIGN.md §14.3). The accelerator (``hayate-accel``, Rust)
must be behaviorally identical for the types it supports; anything it
rejects falls back to the stdlib encoder.
"""

from __future__ import annotations

import json as _json
from importlib import import_module


def _stdlib_dumps(data: object) -> str:
    return _json.dumps(data, ensure_ascii=False, separators=(",", ":"))


try:
    _accel_dumps = import_module("hayate_accel").json_dumps
except ImportError:
    dumps_compact = _stdlib_dumps
else:

    def dumps_compact(data: object) -> str:
        try:
            return str(_accel_dumps(data))
        except TypeError:
            return _stdlib_dumps(data)
