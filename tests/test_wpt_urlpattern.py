"""wpt conformance: URLPattern (pathname component, documented subset).

Vendored data: tests/wpt/urlpatterntestdata.json (see tests/wpt/README.md).

In-scope = the pattern is a single ``{"pathname": ...}`` init dict with at
most one ``{"pathname": ...}`` input, and neither side requires
canonicalization (percent-encoding, dot-segments, non-ASCII) — hayate
matches inputs as given and does not canonicalize (DESIGN.md §4.4).
Matched-``input`` echoes are not compared for the same reason; groups and
match/no-match are. Within scope, patterns the v0.1 subset cannot compile
are *skipped and counted*; everything that compiles must behave exactly
per the test data — the summary hard-fails on any mismatch and ratchets
the pass count.
"""

import json
import re
from collections import Counter
from pathlib import Path

import pytest

from hayate import URLPattern

_DATA = json.loads((Path(__file__).parent / "wpt" / "urlpatterntestdata.json").read_text())

# Ratchet floor — raise deliberately when the supported subset grows.
# 2026-07-22: 54 pass, 79 unsupported-syntax (mostly {} groups and +/*
# modifiers), 0 fail, of 133 in-scope cases.
MIN_PASS = 54

# Segments needing canonicalization before matching: dot-segments,
# percent-encoding, or non-ASCII code points.
_NEEDS_CANONICALIZATION = re.compile(r"(?:^|/)\.\.?(?:/|$)|%|[^\x00-\x7f]")

# Regexp groups are interpreted with Python's `re`; JS-only regexp syntax
# (v-mode set operations, nested character classes) is out of scope.
_JS_ONLY_REGEX = re.compile(r"\[[^\]]*\[|&&|--")


def _needs_canonicalization(case: dict) -> bool:
    strings = [case["pattern"][0]["pathname"]]
    strings += [item.get("pathname", "") for item in case.get("inputs", [])]
    return any(_NEEDS_CANONICALIZATION.search(s) for s in strings)


def _in_scope(case: dict) -> bool:
    pattern = case.get("pattern")
    if not (
        isinstance(pattern, list)
        and len(pattern) == 1
        and isinstance(pattern[0], dict)
        and set(pattern[0]) == {"pathname"}
    ):
        return False
    inputs = case.get("inputs", [])
    if len(inputs) > 1:
        return False
    if not all(isinstance(item, dict) and set(item) <= {"pathname"} for item in inputs):
        return False
    if inputs and "expected_match" not in case:
        return False  # match expectation not spelled out; nothing to verify
    if not inputs and case.get("expected_obj") != "error":
        return False  # canonicalization-only case; we do not model canonical form
    if case.get("expected_match") == "error":
        return False  # input canonicalization errors are not modeled
    if _needs_canonicalization(case):
        return False
    return _JS_ONLY_REGEX.search(case["pattern"][0]["pathname"]) is None


_IN_SCOPE = [(index, case) for index, case in enumerate(_DATA) if _in_scope(case)]


def _run(case: dict) -> tuple[str, str | None]:
    pathname = case["pattern"][0]["pathname"]
    expects_error = case.get("expected_obj") == "error"
    try:
        pattern = URLPattern(pathname)
    except ValueError as exc:
        if expects_error:
            return "pass", None
        return "unsupported", f"{pathname!r}: {exc}"
    if expects_error:
        return "fail", f"{pathname!r}: expected a construction error"
    inputs = case.get("inputs", [])
    if not inputs:
        return "pass", None
    input_pathname = inputs[0].get("pathname", "")
    expected = case["expected_match"]
    result = pattern.exec(input_pathname)
    if expected is None:
        if result is not None:
            return "fail", f"{pathname!r} x {input_pathname!r}: expected no match"
        return "pass", None
    if result is None:
        return "fail", f"{pathname!r} x {input_pathname!r}: expected a match"
    expected_pathname = expected.get("pathname", {})
    if result.pathname.groups != expected_pathname.get("groups", {}):
        return "fail", (
            f"{pathname!r} x {input_pathname!r}: groups {result.pathname.groups!r}"
            f" != {expected_pathname.get('groups')!r}"
        )
    return "pass", None


@pytest.mark.parametrize(("index", "case"), _IN_SCOPE, ids=[str(i) for i, _ in _IN_SCOPE])
def test_wpt_urlpattern_case(index: int, case: dict) -> None:
    status, detail = _run(case)
    if status == "unsupported":
        pytest.skip(f"outside the v0.1 pattern subset: {detail}")
    assert status == "pass", detail


def test_wpt_urlpattern_coverage_summary() -> None:
    statuses = Counter(status for status, _ in (_run(case) for _, case in _IN_SCOPE))
    print(
        f"\nwpt urlpattern: {len(_DATA)} cases total; in-scope {len(_IN_SCOPE)}; "
        f"pass {statuses['pass']}; unsupported-syntax {statuses['unsupported']}; "
        f"fail {statuses['fail']}"
    )
    assert statuses["fail"] == 0
    assert statuses["pass"] >= MIN_PASS, f"ratchet regressed: {statuses['pass']} < {MIN_PASS}"
