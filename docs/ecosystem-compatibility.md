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

[`hayate-admin`](https://github.com/hayatepy/hayate-admin) is a pre-release,
first-party ecosystem package rather than part of the core-wheel compatibility
gate above. At commit
[`3690c75`](https://github.com/hayatepy/hayate-admin/commit/3690c75ea2d02db50b623fd4459b636f2baefa14),
its explicit resource contract covers CRUD, search, declared filters and
sorting, bounded bulk actions, and separately authorized redacted object
history. The same generated checked-SQL definition runs against local SQLite
and native Cloudflare Workers/D1 without ASGI.

The recorded main-branch gates passed
[unit, typing, and distribution checks](https://github.com/hayatepy/hayate-admin/actions/runs/30282559357)
and the
[Chromium flow](https://github.com/hayatepy/hayate-admin/actions/runs/30282559819).
General Django admin parity is not claimed: explicit relationship choices,
bounded autocomplete, and inline editing remain tracked in
[`hayate-admin#9`](https://github.com/hayatepy/hayate-admin/issues/9).

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
