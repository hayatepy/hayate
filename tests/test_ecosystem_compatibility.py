"""Cross-repository compatibility orchestrator tests."""

import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType

import pytest

ROOT = Path(__file__).parents[1]


def _load_module(name: str, path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


runner = _load_module(
    "ecosystem_compatibility_runner",
    ROOT / "benchmarks/ecosystem/runner.py",
)


def test_exact_wheel_provenance_is_accepted(tmp_path):
    wheel = tmp_path / "hayate-0.11.0-py3-none-any.whl"
    wheel.write_bytes(b"wheel under test")
    digest = runner._sha256(wheel)
    direct_url = json.dumps(
        {
            "archive_info": {"hashes": {"sha256": digest}},
            "url": wheel.resolve().as_uri(),
        }
    )

    runner.validate_wheel_provenance(direct_url, wheel, digest)


def test_known_incompatible_fixture_is_rejected(tmp_path):
    wheel = tmp_path / "hayate-0.11.0-py3-none-any.whl"
    wheel.write_bytes(b"wheel under test")
    incompatible = (ROOT / "tests/fixtures/ecosystem/incompatible-direct-url.json").read_text()

    with pytest.raises(runner.CompatibilityError, match="came from"):
        runner.validate_wheel_provenance(incompatible, wheel, runner._sha256(wheel))


def test_recorded_wheel_digest_must_match(tmp_path):
    wheel = tmp_path / "hayate-0.11.0-py3-none-any.whl"
    wheel.write_bytes(b"wheel under test")
    direct_url = json.dumps(
        {
            "archive_info": {"hashes": {"sha256": "0" * 64}},
            "url": wheel.resolve().as_uri(),
        }
    )

    with pytest.raises(runner.CompatibilityError, match="wheel digest"):
        runner.validate_wheel_provenance(direct_url, wheel, runner._sha256(wheel))


def test_markdown_identifies_failed_package_runtime_and_command():
    report = {
        "status": "failed",
        "mode": "smoke",
        "hayate": {
            "commit": "a" * 40,
            "wheel": "hayate.whl",
            "wheel_sha256": "b" * 64,
        },
        "repositories": [{"name": "hayate-mcp", "commit": "c" * 40}],
        "checks": [
            {
                "target": "hayate-mcp",
                "runtime": "workerd",
                "name": "MCP server",
                "command": "bash scripts/check_workerd.sh",
                "status": "failed",
                "duration_seconds": 1.25,
                "output_tail": "incompatible API",
            }
        ],
    }

    markdown = runner.render_markdown(report)

    assert "hayate-mcp / workerd / MCP server" in markdown
    assert "bash scripts/check_workerd.sh" in markdown
    assert "incompatible API" in markdown


def test_reference_parser_rejects_unknown_repositories():
    with pytest.raises(runner.argparse.ArgumentTypeError):
        runner._parse_references(["unknown=deadbeef"])


def test_workerd_target_requires_node_24(tmp_path, monkeypatch):
    run = runner.CompatibilityRun(
        mode="smoke",
        targets=(),
        references={},
        repository_base="https://example.invalid",
        output=tmp_path / "report.json",
        workspace=tmp_path,
    )
    monkeypatch.setattr(
        runner.subprocess,
        "run",
        lambda *_args, **_kwargs: runner.subprocess.CompletedProcess(
            ["node", "--version"], 0, "v26.0.0\n"
        ),
    )

    assert run.verify_node_24() is False
    assert run.checks[-1].status == "failed"


def test_workerd_environment_does_not_inherit_outer_python(tmp_path, monkeypatch):
    wheel = tmp_path / "hayate.whl"
    monkeypatch.setenv("UV_PYTHON", "3.14")
    monkeypatch.setenv("VIRTUAL_ENV", "/outer/.venv")

    env = runner._workerd_environment(wheel)

    assert "UV_PYTHON" not in env
    assert "VIRTUAL_ENV" not in env
    assert env["HAYATE_ECOSYSTEM_WHEEL"] == str(wheel)
