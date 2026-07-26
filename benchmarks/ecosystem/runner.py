"""Cross-repository compatibility gate for the Hayate ecosystem.

The runner builds the current Hayate wheel, clones each public ecosystem
repository into a disposable workspace, and replaces only the installed
Hayate distribution. Committed lock files remain unchanged.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import platform
import shlex
import subprocess
import sys
import tempfile
import time
import urllib.parse
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
DEFAULT_OUTPUT = ROOT / ".benchmark" / "ecosystem" / "latest.json"
DEFAULT_REPOSITORY_BASE = "https://github.com/hayatepy"
OUTPUT_TAIL_LIMIT = 8_000

_PROVENANCE_SCRIPT = """
import importlib.metadata as metadata
distribution = metadata.distribution("hayate")
direct_url = distribution.read_text("direct_url.json")
if direct_url is None:
    raise SystemExit("installed Hayate has no direct_url.json")
print(direct_url)
""".strip()


class CompatibilityError(RuntimeError):
    """Raised when the environment does not contain the wheel under test."""


@dataclass(frozen=True, slots=True)
class Target:
    """One public ecosystem repository."""

    name: str
    repository: str
    mypy_paths: tuple[str, ...]
    uses_core_directly: bool = True


TARGETS = (
    Target("hayate-auth", "hayate-auth", ("src",)),
    Target("hayate-fetch", "hayate-fetch", ("src",)),
    Target("hayate-mcp", "hayate-mcp", ("src",)),
    Target("hayate-openapi", "hayate-openapi", ("src", "examples")),
    Target("create-hayate", "create-hayate", ("src",), uses_core_directly=False),
)
TARGET_BY_NAME = {target.name: target for target in TARGETS}


@dataclass(slots=True)
class CheckResult:
    """One setup or compatibility command."""

    target: str
    runtime: str
    name: str
    command: str
    status: str
    duration_seconds: float
    output_tail: str | None = None


@dataclass(slots=True)
class RepositoryResult:
    """Resolved repository identity used by a run."""

    name: str
    url: str
    commit: str | None


def _display_command(command: list[str]) -> str:
    return shlex.join(command)


def _output_tail(output: str) -> str | None:
    stripped = output.strip()
    if not stripped:
        return None
    return stripped[-OUTPUT_TAIL_LIMIT:]


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def validate_wheel_provenance(
    direct_url_text: str,
    expected_wheel: Path,
    expected_sha256: str,
) -> None:
    """Reject an environment unless PEP 610 identifies the exact input wheel."""

    try:
        direct_url = json.loads(direct_url_text)
        url = direct_url["url"]
    except (json.JSONDecodeError, KeyError, TypeError) as error:
        raise CompatibilityError("invalid Hayate direct_url.json") from error

    parsed = urllib.parse.urlparse(url)
    if parsed.scheme != "file" or parsed.netloc not in ("", "localhost"):
        raise CompatibilityError(f"Hayate was not installed from a local wheel: {url}")
    installed_from = Path(urllib.parse.unquote(parsed.path)).resolve()
    if installed_from != expected_wheel.resolve():
        raise CompatibilityError(
            f"Hayate came from {installed_from}, expected {expected_wheel.resolve()}"
        )

    archive_info = direct_url.get("archive_info", {})
    hashes = archive_info.get("hashes", {})
    recorded_sha256 = hashes.get("sha256")
    legacy_hash = archive_info.get("hash")
    if recorded_sha256 is None and isinstance(legacy_hash, str):
        prefix = "sha256="
        if legacy_hash.startswith(prefix):
            recorded_sha256 = legacy_hash.removeprefix(prefix)
    # PEP 610 permits an empty archive_info object, and uv currently omits the
    # digest for a direct local wheel. When a frontend records one, ratchet it
    # against the independently computed artifact digest.
    if recorded_sha256 is not None and recorded_sha256 != expected_sha256:
        raise CompatibilityError(
            f"Hayate wheel digest is {recorded_sha256!r}, expected {expected_sha256}"
        )


def _python_executable(repository: Path) -> Path:
    directory = "Scripts" if os.name == "nt" else "bin"
    executable = "python.exe" if os.name == "nt" else "python"
    return repository / ".venv" / directory / executable


def _workerd_environment(wheel: Path) -> dict[str, str]:
    """Isolate Workers' pinned Python from the outer CPython test runtime."""

    env = os.environ.copy()
    # setup-uv exports UV_PYTHON for the job, while Workers projects pin
    # CPython/Pyodide 3.13 themselves. A parent venv has the same precedence
    # problem for generated projects, so neither may cross this boundary.
    env.pop("UV_PYTHON", None)
    env.pop("VIRTUAL_ENV", None)
    env["HAYATE_ECOSYSTEM_WHEEL"] = str(wheel)
    return env


class CompatibilityRun:
    """Stateful compatibility run that always produces an audit artifact."""

    def __init__(
        self,
        *,
        mode: str,
        targets: tuple[Target, ...],
        references: dict[str, str],
        repository_base: str,
        output: Path,
        workspace: Path,
    ) -> None:
        self.mode = mode
        self.targets = targets
        self.references = references
        self.repository_base = repository_base.rstrip("/")
        self.output = output
        self.workspace = workspace
        self.checks: list[CheckResult] = []
        self.repositories: list[RepositoryResult] = []
        self.started_at = dt.datetime.now(dt.UTC)
        self.wheel: Path | None = None
        self.wheel_sha256: str | None = None
        self.node_24_ready = True

    def run_command(
        self,
        *,
        target: str,
        runtime: str,
        name: str,
        command: list[str],
        cwd: Path,
        env: dict[str, str] | None = None,
        timeout: int = 900,
    ) -> subprocess.CompletedProcess[str] | None:
        """Run and record one command, retaining output only on failure."""

        print(f"[{target}/{runtime}] {name}", flush=True)
        started = time.perf_counter()
        output = ""
        status = "passed"
        try:
            completed = subprocess.run(
                command,
                cwd=cwd,
                env=env,
                check=False,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                timeout=timeout,
            )
            output = completed.stdout
            if completed.returncode != 0:
                status = "failed"
        except subprocess.TimeoutExpired as error:
            completed = None
            status = "failed"
            stdout = error.stdout or ""
            output = f"{stdout}\ncommand timed out after {timeout} seconds"
        except OSError as error:
            completed = None
            status = "failed"
            output = str(error)
        duration = round(time.perf_counter() - started, 3)
        failure_output = _output_tail(output) if status == "failed" else None
        self.checks.append(
            CheckResult(
                target=target,
                runtime=runtime,
                name=name,
                command=_display_command(command),
                status=status,
                duration_seconds=duration,
                output_tail=failure_output,
            )
        )
        if status == "failed":
            if failure_output:
                print(failure_output, file=sys.stderr, flush=True)
            return None
        return completed

    def skip(self, *, target: str, runtime: str, name: str, reason: str) -> None:
        """Record a dependent check that could not safely run."""

        self.checks.append(
            CheckResult(
                target=target,
                runtime=runtime,
                name=name,
                command="",
                status="skipped",
                duration_seconds=0.0,
                output_tail=reason,
            )
        )

    def build_wheel(self) -> bool:
        """Build the exact core commit under test."""

        wheel_directory = self.workspace / "wheel"
        wheel_directory.mkdir(parents=True)
        completed = self.run_command(
            target="hayate",
            runtime="build",
            name="build wheel",
            command=["uv", "build", "--wheel", "--out-dir", str(wheel_directory)],
            cwd=ROOT,
        )
        if completed is None:
            return False
        wheels = sorted(wheel_directory.glob("hayate-*.whl"))
        if len(wheels) != 1:
            self.checks.append(
                CheckResult(
                    target="hayate",
                    runtime="build",
                    name="identify wheel",
                    command=f"find {wheel_directory} -name 'hayate-*.whl'",
                    status="failed",
                    duration_seconds=0.0,
                    output_tail=f"expected one Hayate wheel, found {len(wheels)}",
                )
            )
            return False
        self.wheel = wheels[0].resolve()
        self.wheel_sha256 = _sha256(self.wheel)
        return True

    def verify_node_24(self) -> bool:
        """Require the runtime used by every real workerd contract."""

        completed = self.run_command(
            target="ecosystem",
            runtime="workerd",
            name="verify Node.js 24",
            command=["node", "--version"],
            cwd=ROOT,
        )
        if completed is None:
            self.node_24_ready = False
            return False
        version = completed.stdout.strip()
        if not version.startswith("v24."):
            self.checks[-1].status = "failed"
            self.checks[-1].output_tail = f"expected Node.js 24, got {version}"
            print(self.checks[-1].output_tail, file=sys.stderr, flush=True)
            self.node_24_ready = False
            return False
        return True

    def clone_target(self, target: Target) -> Path | None:
        """Clone a target HEAD, optionally checking out an exact reported ref."""

        repositories = self.workspace / "repositories"
        repositories.mkdir(exist_ok=True)
        destination = repositories / target.repository
        url = f"{self.repository_base}/{target.repository}.git"
        cloned = self.run_command(
            target=target.name,
            runtime="git",
            name="clone repository",
            command=["git", "clone", "--depth", "1", url, str(destination)],
            cwd=self.workspace,
        )
        if cloned is None:
            self.repositories.append(RepositoryResult(target.name, url, None))
            return None

        reference = self.references.get(target.name)
        if reference is not None:
            fetched = self.run_command(
                target=target.name,
                runtime="git",
                name="fetch requested ref",
                command=["git", "fetch", "--depth", "1", "origin", reference],
                cwd=destination,
            )
            if fetched is None:
                self.repositories.append(RepositoryResult(target.name, url, None))
                return None
            checked_out = self.run_command(
                target=target.name,
                runtime="git",
                name="checkout requested ref",
                command=["git", "checkout", "--detach", "FETCH_HEAD"],
                cwd=destination,
            )
            if checked_out is None:
                self.repositories.append(RepositoryResult(target.name, url, None))
                return None

        commit_result = self.run_command(
            target=target.name,
            runtime="git",
            name="resolve commit",
            command=["git", "rev-parse", "HEAD"],
            cwd=destination,
        )
        commit = commit_result.stdout.strip() if commit_result is not None else None
        self.repositories.append(RepositoryResult(target.name, url, commit))
        return destination if commit is not None else None

    def prepare_python(self, target: Target, repository: Path) -> bool:
        """Create the locked environment and inject the local Hayate wheel."""

        synced = self.run_command(
            target=target.name,
            runtime="cpython",
            name="sync locked environment",
            command=["uv", "sync", "--locked"],
            cwd=repository,
        )
        if synced is None:
            return False
        if not target.uses_core_directly:
            return True

        assert self.wheel is not None
        installed = self.run_command(
            target=target.name,
            runtime="cpython",
            name="install Hayate wheel under test",
            command=[
                "uv",
                "pip",
                "install",
                "--python",
                str(_python_executable(repository)),
                "--reinstall-package",
                "hayate",
                "--no-deps",
                str(self.wheel),
            ],
            cwd=repository,
        )
        if installed is None:
            return False

        provenance = self.run_command(
            target=target.name,
            runtime="cpython",
            name="verify Hayate wheel provenance",
            command=[str(_python_executable(repository)), "-c", _PROVENANCE_SCRIPT],
            cwd=repository,
        )
        if provenance is None:
            return False
        assert self.wheel_sha256 is not None
        try:
            validate_wheel_provenance(provenance.stdout, self.wheel, self.wheel_sha256)
        except CompatibilityError as error:
            self.checks[-1].status = "failed"
            self.checks[-1].output_tail = str(error)
            print(str(error), file=sys.stderr, flush=True)
            return False
        return True

    def run_python_contract(self, target: Target, repository: Path) -> None:
        """Run the ecosystem package's unit and strict typing contract."""

        python = str(_python_executable(repository))
        self.run_command(
            target=target.name,
            runtime="cpython",
            name="unit contract",
            command=[python, "-m", "pytest", "-q"],
            cwd=repository,
        )
        self.run_command(
            target=target.name,
            runtime="cpython",
            name="type contract",
            command=[python, "-m", "mypy", *target.mypy_paths],
            cwd=repository,
        )

    def run_workerd_contracts(self, target: Target, repository: Path) -> None:
        """Run the Workers-facing gates against real workerd."""

        if not self.node_24_ready:
            self.skip(
                target=target.name,
                runtime="workerd",
                name="runtime contracts",
                reason="Node.js 24 prerequisite failed",
            )
            return
        assert self.wheel is not None
        env = _workerd_environment(self.wheel)
        if target.name == "hayate-mcp":
            self.run_command(
                target=target.name,
                runtime="workerd",
                name="MCP server",
                command=["bash", "scripts/check_workerd.sh"],
                cwd=repository,
                env=env,
            )
        elif target.name == "create-hayate":
            self.run_command(
                target=target.name,
                runtime="workerd",
                name="generated Workers app",
                command=["bash", "scripts/check_workers_template.sh", "workers"],
                cwd=repository,
                env=env,
            )
            if self.mode == "full":
                self.run_command(
                    target=target.name,
                    runtime="workerd",
                    name="generated MCP server",
                    command=["bash", "scripts/check_workers_template.sh", "mcp"],
                    cwd=repository,
                    env=env,
                )

    def run_target(self, target: Target) -> None:
        """Run all selected contracts for one repository."""

        repository = self.clone_target(target)
        if repository is None:
            self.skip(
                target=target.name,
                runtime="cpython",
                name="compatibility contracts",
                reason="repository checkout failed",
            )
            return
        if not self.prepare_python(target, repository):
            self.skip(
                target=target.name,
                runtime="cpython",
                name="compatibility contracts",
                reason="environment preparation failed",
            )
            return
        self.run_python_contract(target, repository)
        if target.name in {"hayate-mcp", "create-hayate"}:
            self.run_workerd_contracts(target, repository)

    def result(self) -> dict[str, Any]:
        """Return the stable report schema."""

        finished_at = dt.datetime.now(dt.UTC)
        failed = any(check.status == "failed" for check in self.checks)
        core_commit = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=ROOT,
            check=True,
            text=True,
            stdout=subprocess.PIPE,
        ).stdout.strip()
        return {
            "schema_version": 1,
            "status": "failed" if failed else "passed",
            "mode": self.mode,
            "started_at": self.started_at.isoformat(),
            "finished_at": finished_at.isoformat(),
            "duration_seconds": round((finished_at - self.started_at).total_seconds(), 3),
            "hayate": {
                "commit": core_commit,
                "wheel": self.wheel.name if self.wheel is not None else None,
                "wheel_sha256": self.wheel_sha256,
            },
            "environment": {
                "python": platform.python_version(),
                "implementation": platform.python_implementation(),
                "platform": platform.platform(),
                "machine": platform.machine(),
                "node": _tool_version(["node", "--version"]),
                "uv": _tool_version(["uv", "--version"]),
            },
            "repositories": [asdict(repository) for repository in self.repositories],
            "checks": [asdict(check) for check in self.checks],
        }

    def write_report(self) -> dict[str, Any]:
        """Write both JSON and compact Markdown reports."""

        report = self.result()
        self.output.parent.mkdir(parents=True, exist_ok=True)
        self.output.write_text(json.dumps(report, indent=2) + "\n")
        markdown_output = self.output.with_suffix(".md")
        markdown_output.write_text(render_markdown(report))
        return report


def _tool_version(command: list[str]) -> str | None:
    try:
        return subprocess.run(
            command,
            check=True,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        ).stdout.strip()
    except (FileNotFoundError, subprocess.CalledProcessError):
        return None


def render_markdown(report: dict[str, Any]) -> str:
    """Render the compact human review artifact."""

    hayate = report["hayate"]
    lines = [
        "# Hayate ecosystem compatibility",
        "",
        f"- Status: **{report['status']}**",
        f"- Mode: `{report['mode']}`",
        f"- Hayate commit: `{hayate['commit']}`",
        f"- Wheel: `{hayate['wheel']}`",
        f"- Wheel SHA-256: `{hayate['wheel_sha256']}`",
        "",
        "## Repository heads",
        "",
        "| Repository | Commit |",
        "|---|---|",
    ]
    lines.extend(
        f"| {repository['name']} | `{repository['commit'] or 'unresolved'}` |"
        for repository in report["repositories"]
    )
    lines.extend(
        [
            "",
            "## Checks",
            "",
            "| Target | Runtime | Check | Status | Seconds |",
            "|---|---|---|---|---:|",
        ]
    )
    lines.extend(
        "| {target} | {runtime} | {name} | {status} | {duration_seconds:.3f} |".format(**check)
        for check in report["checks"]
    )
    failures = [check for check in report["checks"] if check["status"] == "failed"]
    if failures:
        lines.extend(["", "## Failures", ""])
        for check in failures:
            lines.extend(
                [
                    f"### {check['target']} / {check['runtime']} / {check['name']}",
                    "",
                    f"Command: `{check['command']}`",
                    "",
                    "```text",
                    check["output_tail"] or "(no output)",
                    "```",
                    "",
                ]
            )
    return "\n".join(lines).rstrip() + "\n"


def _parse_references(values: list[str]) -> dict[str, str]:
    references: dict[str, str] = {}
    for value in values:
        name, separator, reference = value.partition("=")
        if not separator or name not in TARGET_BY_NAME or not reference:
            choices = ", ".join(TARGET_BY_NAME)
            raise argparse.ArgumentTypeError(
                f"--ref must be NAME=REF where NAME is one of: {choices}"
            )
        references[name] = reference
    return references


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("smoke", "full"))
    parser.add_argument(
        "--target",
        action="append",
        choices=tuple(TARGET_BY_NAME),
        dest="targets",
        help="run only this target; repeat to select multiple targets",
    )
    parser.add_argument(
        "--ref",
        action="append",
        default=[],
        metavar="NAME=REF",
        help="reproduce a reported target commit instead of its default-branch HEAD",
    )
    parser.add_argument(
        "--repository-base",
        default=DEFAULT_REPOSITORY_BASE,
        help="base URL containing the public ecosystem repositories",
    )
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument(
        "--work-dir",
        type=Path,
        help="keep an isolated workspace at this new or empty directory",
    )
    return parser


def _workspace(path: Path | None) -> tuple[Path, tempfile.TemporaryDirectory[str] | None]:
    if path is None:
        temporary = tempfile.TemporaryDirectory(prefix="hayate-ecosystem-")
        return Path(temporary.name), temporary
    resolved = path.resolve()
    if resolved.exists() and not resolved.is_dir():
        raise CompatibilityError(f"--work-dir must be a directory: {resolved}")
    if resolved.exists() and any(resolved.iterdir()):
        raise CompatibilityError(f"--work-dir must be new or empty: {resolved}")
    resolved.mkdir(parents=True, exist_ok=True)
    return resolved, None


def main(argv: list[str] | None = None) -> int:
    """Run the requested compatibility profile."""

    args = _parser().parse_args(argv)
    try:
        references = _parse_references(args.ref)
        workspace, temporary = _workspace(args.work_dir)
    except (argparse.ArgumentTypeError, CompatibilityError) as error:
        print(error, file=sys.stderr)
        return 2
    selected_names = tuple(dict.fromkeys(args.targets)) if args.targets else ()
    selected = tuple(TARGET_BY_NAME[name] for name in selected_names) if selected_names else TARGETS
    run = CompatibilityRun(
        mode=args.mode,
        targets=selected,
        references=references,
        repository_base=args.repository_base,
        output=args.output.resolve(),
        workspace=workspace,
    )
    try:
        if any(target.name in {"hayate-mcp", "create-hayate"} for target in selected):
            run.verify_node_24()
        if run.build_wheel():
            for target in selected:
                run.run_target(target)
        else:
            for target in selected:
                run.skip(
                    target=target.name,
                    runtime="all",
                    name="compatibility contracts",
                    reason="Hayate wheel build failed",
                )
        report = run.write_report()
    finally:
        if temporary is not None:
            temporary.cleanup()
    print(f"report: {run.output}", flush=True)
    print(f"summary: {run.output.with_suffix('.md')}", flush=True)
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
