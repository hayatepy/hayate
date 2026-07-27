# Ecosystem compatibility

Hayate tests its public ecosystem against the wheel built from the exact core
commit under review. This closes the gap between each package's independently
locked PyPI environment and the combination users will run after a core
release.

The gate covers:

- `hayate-auth`
- `hayate-fetch`
- `hayate-mcp`
- `hayate-openapi`
- the `create-hayate` Workers templates

For packages that import Hayate directly, the runner creates the repository's
locked environment, replaces only Hayate with the unpublished wheel, verifies
the wheel path through its PEP 610 metadata, records the artifact SHA-256, and
then runs the package's unit and strict typing contracts. It never edits a
checked-out lock file.

The Workers contracts use Node.js 24 and start real workerd instances. The MCP
package exercises its server directly. `create-hayate` generates a fresh app,
tests the generated CPython environment with the same wheel, injects that wheel
into the Pyodide bundle after pywrangler's locked sync, and drives the live
Worker over HTTP. The scheduled full profile also covers the generated MCP
Worker.

## First-party administration evidence

[`hayate-admin`](https://github.com/hayatepy/hayate-admin) is a versioned,
first-party ecosystem package rather than part of the core-wheel compatibility
gate above. At the tagged 0.2.0 commit
[`2fdc1c6`](https://github.com/hayatepy/hayate-admin/commit/2fdc1c6349308157f1cbea0ac1aff11a42c0d023),
its explicit resource contract covers CRUD, search, declared filters and
sorting, bounded bulk actions, and separately authorized redacted object
history. It also covers searchable to-one relationship choices and bounded
reverse inline create/update/delete with exact parent/child authorization,
preloaded labels, tenant-scoped ID resolution, and repository-owned atomic
writes. Version 0.2 adds static saved views, query-bound forward keyset
continuations, and separately authorized CSV callbacks with field allowlists,
per-object authorization, spreadsheet-formula neutralization, and exact
row/UTF-8-byte ceilings. The same generated checked-SQL definition runs against
local SQLite and native Cloudflare Workers/D1 without ASGI.

The recorded main-branch gates passed
[unit, typing, 25 generated SQL queries, native D1, and distribution checks](https://github.com/hayatepy/hayate-admin/actions/runs/30292195326)
and the
[Chromium flow](https://github.com/hayatepy/hayate-admin/actions/runs/30292194366).
The offline generator then carried the exact snapshot and owner-scoped cursor
and export SQL into fresh projects in
[`create-hayate#46`](https://github.com/hayatepy/create-hayate/pull/46);
[its matrix](https://github.com/hayatepy/create-hayate/actions/runs/30293451580)
proved class/global Workers and D1. General Django admin parity is not claimed:
Django retains ORM-derived configuration, many-to-many/generic relationship
breadth, and a much more mature extension ecosystem. Hayate's narrower
first-party advantage is the ready-made combination of saved views, keyset
continuations, and bounded, independently authorized CSV export.

Main commit
[`aedd4c4`](https://github.com/hayatepy/hayate-admin/commit/aedd4c47cbbe7c7d26cdf39b6c65fa201996369d)
then adds immutable per-site message catalogs with English defaults and
localized package navigation, forms, validation, history, relationship, bulk,
empty, and error states. Branding accepts only escaped plain text and
contrast-checked color/density tokens; the deterministic stylesheet is
authorized by an exact CSP hash rather than `unsafe-inline`. Landmarks, skip
navigation, visible focus, reduced-motion behavior, labels, tables, and live
status/error semantics are exercised with pinned axe-core 4.12.1 at each real
CRUD, relationship, inline, bulk, saved-view, history, and delete state.

The exact merge passed
[Python 3.12-3.14, SQLite, native D1, package, dependency, and workflow checks](https://github.com/hayatepy/hayate-admin/actions/runs/30295637986),
[Chromium plus WCAG A/AA axe checks](https://github.com/hayatepy/hayate-admin/actions/runs/30295638023),
and
[CodeQL](https://github.com/hayatepy/hayate-admin/actions/runs/30295638207).
The native Workers/D1 upload was 1257.86 KiB / gzip 287.47 KiB. This surface is
merged but not yet a stable/publication claim: the package's PyPI Trusted
Publisher registration and external adoption evidence remain outstanding.

## Reproduce

Prerequisites are CPython 3.12 or newer, uv, Git, Node.js 24, and the normal
build tools required by the ecosystem projects.

Run the pull-request profile:

```sh
python3 benchmarks/ecosystem/runner.py smoke
```

Run the scheduled profile:

```sh
python3 benchmarks/ecosystem/runner.py full
```

Both commands clone public repositories into a disposable temporary directory.
Use `--work-dir .benchmark/ecosystem/work` to retain the isolated checkouts for
debugging. Use `--target hayate-mcp` to narrow a local diagnosis.

Every report records the resolved default-branch commit for each repository.
An exact run can be repeated by supplying those commits:

```sh
python3 benchmarks/ecosystem/runner.py full \
  --ref hayate-auth=<commit> \
  --ref hayate-fetch=<commit> \
  --ref hayate-mcp=<commit> \
  --ref hayate-openapi=<commit> \
  --ref create-hayate=<commit>
```

JSON and Markdown artifacts are written to
`.benchmark/ecosystem/latest.{json,md}` by default. A failed artifact names the
package, runtime, check, exact command, and the tail of its output. A run exits
successfully only when every selected compatibility check passes.

## Policy

- Pull requests that change the core, its dependencies, or this gate run the
  bounded `smoke` profile.
- The `full` profile runs weekly and is also available through manual workflow
  dispatch.
- Ecosystem repositories are always tested at their public default-branch
  heads unless explicit `--ref` values reproduce a prior report.
- A release is not compatible merely because dependency resolution succeeds:
  the installed wheel provenance, package contracts, and runtime boot must all
  pass.
- A failing ecosystem head blocks a core release until the core change is made
  compatible or the affected package deliberately updates its public contract.
