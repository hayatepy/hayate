"""Compact JSON serialization, with the optional Tier 2 accelerator.

The implementation is selected once at import time so call sites stay
monomorphic (DESIGN.md §14.3). The accelerator (``hayate-accel``, Rust)
must be behaviorally identical for the types it supports; anything it
rejects falls back to the stdlib encoder.
"""

from __future__ import annotations

import json as _json
from importlib import import_module

_encode_compact = _json.JSONEncoder(ensure_ascii=False, separators=(",", ":")).encode
_encode_string = _json.encoder.encode_basestring


def _stdlib_dumps(data: object) -> str:
    if type(data) is dict:
        parts: list[str] = []
        for key, value in data.items():
            if type(key) is not str:
                break
            encoded_key = _encode_string(key)
            if type(value) is str:
                encoded_value = _encode_string(value)
            elif value is None:
                encoded_value = "null"
            elif value is True:
                encoded_value = "true"
            elif value is False:
                encoded_value = "false"
            elif type(value) is int:
                encoded_value = str(value)
            else:
                break
            parts.append(f"{encoded_key}:{encoded_value}")
        else:
            if len(parts) == 1:
                return f"{{{parts[0]}}}"
            if len(parts) == 2:
                return f"{{{parts[0]},{parts[1]}}}"
            return "{" + ",".join(parts) + "}"
    return _encode_compact(data)


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
