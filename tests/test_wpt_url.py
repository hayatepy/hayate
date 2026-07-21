"""wpt conformance: URL parsing, measured against the documented subset.

Vendored data: tests/wpt/urltestdata.json (see tests/wpt/README.md).

Scope for v0.1: absolute special-scheme URLs (http/https/ws/wss/ftp) with
no base-URL resolution. The suite is a ratchet: the pass count may only
grow. Known gaps are counted as failures rather than hidden — IDNA and
punycode hosts, IPv4/IPv6 canonicalization, and percent-encoding
normalization of paths and userinfo.
"""

import json
import re
from collections import Counter
from pathlib import Path

from hayate import URL

_DATA = json.loads((Path(__file__).parent / "wpt" / "urltestdata.json").read_text())
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
# 2026-07-22: 202/306 in-scope (66.0%). Known gaps: IDNA/punycode,
# IPv4/IPv6 canonicalization, percent-decoded dot-segments (%2e).
MIN_PASS = 202


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
