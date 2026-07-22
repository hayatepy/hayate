# Web standards conformance

hayate claims a *documented subset* of each standard, and measures that
claim against vendored [web-platform-tests](https://github.com/web-platform-tests/wpt)
data on every test run (see `tests/wpt/README.md` for provenance). The
numbers below are enforced as ratchets in CI: they may only go up.

Last measured: 2026-07-22, wpt data pinned per `tests/wpt/README.md`.

## URLPattern (`hayate.URLPattern`)

Scope: pathname component; patterns supplied as `{"pathname": ...}`;
no canonicalization of pattern or input (matching is on the strings as
given); regexp groups are interpreted by Python's `re`.

| Metric | Count |
|---|---|
| wpt cases total | 369 |
| In scope (pathname-only, no canonicalization) | 133 |
| Pass | 54 |
| Rejected as unsupported syntax (explicit `ValueError`) | 79 |
| **Behavioral mismatches within the supported subset** | **0** |

The 79 rejected cases use syntax the v0.1 subset deliberately excludes:
`{}` grouping and `+` / `*` modifiers. They fail loudly at route
registration time, never silently.

## URL (`hayate.URL`)

Scope: absolute special-scheme URLs (http, https, ws, wss, ftp) without
base-URL resolution.

| Metric | Count |
|---|---|
| wpt cases total | 891 |
| In scope (special-scheme, no base) | 306 |
| Pass | **202 (66.0%)** |

Implemented per spec: input preprocessing (C0/space trim, tab/newline
removal), backslash tolerance for special schemes, default-port
elision, dot-segment removal, component percent-encoding for path /
query / fragment / userinfo, forbidden-host-code-point validation.

Known gaps (counted as failures above, not hidden). The 102 in-scope
failures decompose as (measured 2026-07-22):

- Host percent-decode → UTS-46 `domain_to_ascii` pipeline (57 cases) —
  non-ASCII hosts raise `ValueError` instead of converting (explicit
  error over silent mojibake). Full support costs ~310 KiB of UTS-46
  tables, so it waits for demand — if you need it, comment on
  [hayatepy/hayate#2](https://github.com/hayatepy/hayate/issues/2),
  which the error message also points at.
- Stricter host rejection (26) plus IPv4 (`0x7f.1` style, 5) and IPv6
  (9) canonicalization, percent-decoded dot-segments and multi-slash
  edge cases (5) — pure algorithms, no tables; the next planned
  conformance work.

## Headers / Fetch semantics

wpt's Headers suites are JavaScript-harness tests without extractable
JSON vectors, so conformance is covered by hand-written unit tests
mirroring the Fetch Standard's semantics (`tests/test_headers.py`,
`tests/test_request.py`, `tests/test_response.py`).
