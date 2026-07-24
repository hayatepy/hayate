"""wpt conformance: URL parsing, measured against the documented subset.

Vendored data: tests/wpt/urltestdata.json (see tests/wpt/README.md).

Scope: absolute special-scheme URLs (http/https/ws/wss/ftp) with no
base-URL resolution. The complete 306-case scope is a hard ratchet:
percent-decode → UTS-46, IPv4/IPv6 canonicalization, path encoding,
and dot-segment normalization are all implemented.
"""

import json
import re
from collections import Counter
from pathlib import Path

from hayate import URL

_DATA = json.loads((Path(__file__).parent / "wpt" / "urltestdata.json").read_text("utf-8"))
_CASES = [case for case in _DATA if isinstance(case, dict)]
_SPECIAL = ("http", "https", "ws", "wss", "ftp")
_COMPONENTS = (
    "protocol",
    "username",
    "password",
    "hostname",
    "port",
    "pathname",
    "search",
    "hash",
)
_SCHEME_RE = re.compile(r"^[\x00-\x20]*([A-Za-z][A-Za-z0-9+.\-]*):")

# Ratchet floor — raise deliberately when conformance improves.
# 2026-07-24 (0.10.0): 306/306 in-scope (100%) after the complete special-host
# percent-decode -> non-transitional UTS-46 pipeline and path "^" encoding.
MIN_PASS = 306


def _sniff_scheme(raw: str) -> str | None:
    cleaned = raw.replace("\t", "").replace("\n", "").replace("\r", "")
    matched = _SCHEME_RE.match(cleaned)
    return matched.group(1).lower() if matched else None


def _in_scope(case: dict) -> bool:
    if case.get("base") is not None:
        return False
    if case.get("failure"):
        return _sniff_scheme(case["input"]) in _SPECIAL
    return case.get("protocol", "").rstrip(":") in _SPECIAL


def _run(case: dict) -> tuple[str, str | None]:
    if case.get("failure"):
        try:
            URL(case["input"])
        except ValueError:
            return "pass", None
        return "fail", f"{case['input']!r}: expected a parse failure"
    try:
        url = URL(case["input"])
    except ValueError as exc:
        return "fail", f"{case['input']!r}: raised {exc}"
    for component in _COMPONENTS:
        actual = getattr(url, component)
        expected = case[component]
        if actual != expected:
            return "fail", f"{case['input']!r} {component}: {actual!r} != {expected!r}"
    return "pass", None


def test_wpt_url_conformance_ratchet() -> None:
    in_scope = [case for case in _CASES if _in_scope(case)]
    statuses = Counter()
    failures: list[str] = []
    for case in in_scope:
        status, detail = _run(case)
        statuses[status] += 1
        if status == "fail" and detail is not None:
            failures.append(detail)
    rate = statuses["pass"] / len(in_scope) * 100
    print(
        f"\nwpt url: {len(_CASES)} cases total; in-scope {len(in_scope)} "
        f"(special-scheme, no base); pass {statuses['pass']} ({rate:.1f}%)"
    )
    for line in failures[:15]:
        print("  fail:", line)
    assert statuses["pass"] >= MIN_PASS, f"ratchet regressed: {statuses['pass']} < {MIN_PASS}"
