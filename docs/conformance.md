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

Known gaps (counted as failures above, not hidden):

- IDNA / punycode hostnames — non-ASCII hosts raise `ValueError`
  instead of converting (explicit error over silent mojibake)
- IPv4 (`0x7f.1` style) and IPv6 canonicalization
- Percent-decoded dot-segments (`/%2e%2e/`)
- Multi-slash path edge cases (`////../..`)

## Headers / Fetch semantics

wpt's Headers suites are JavaScript-harness tests without extractable
JSON vectors, so conformance is covered by hand-written unit tests
mirroring the Fetch Standard's semantics (`tests/test_headers.py`,
`tests/test_request.py`, `tests/test_response.py`).
