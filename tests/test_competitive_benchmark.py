"""Competitive benchmark boundary tests."""

import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType

ROOT = Path(__file__).parents[1]


def _load_module(name: str, path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


raw_asgi = _load_module(
    "competitive_raw_asgi",
    ROOT / "benchmarks/competitive/apps/hayate/raw_asgi.py",
).app
competitive_runner = _load_module(
    "competitive_runner",
    ROOT / "benchmarks/competitive/runner.py",
)
competitive_publish = _load_module(
    "competitive_publish",
    ROOT / "benchmarks/competitive/publish.py",
)
_locked_node_package_version = competitive_runner._locked_node_package_version
_render_markdown = competitive_runner.render_markdown
_setup = competitive_runner.setup
_transport_profile = competitive_runner._transport_profile


async def _raw_request(method: str, path: str, body: bytes = b"") -> tuple[int, bytes]:
    messages: list[dict] = []

    async def receive():
        return {"type": "http.request", "body": body, "more_body": False}

    async def send(message):
        messages.append(message)

    await raw_asgi(
        {"type": "http", "method": method, "path": path},
        receive,
        send,
    )
    return messages[0]["status"], messages[1]["body"]


async def test_raw_asgi_executes_the_common_workload():
    assert await _raw_request("GET", "/text") == (200, b"hello")
    assert await _raw_request("GET", "/items/123") == (
        200,
        b'{"id":"123","name":"item-123"}',
    )
    assert await _raw_request("GET", "/route63/value") == (200, b"ok")
    assert await _raw_request(
        "POST",
        "/echo",
        b'{"message":"hello"}',
    ) == (200, b'{"message":"hello","length":5}')


def test_node_transport_version_comes_from_lockfile():
    assert _locked_node_package_version("@hono/node-server") == "2.0.12"


def test_setup_rebuilds_the_current_hayate_checkout(monkeypatch):
    commands: list[list[str]] = []

    def record(command, **_kwargs):
        commands.append(command)

    monkeypatch.setattr(competitive_runner, "_run_checked", record)
    monkeypatch.setattr(competitive_runner, "_install_oha", lambda: None)

    _setup()

    hayate = next(command for command in commands if "apps/hayate" in " ".join(command))
    assert hayate[-2:] == ["--reinstall-package", "hayate"]
    assert all(
        "--reinstall-package" not in command for command in commands if command is not hayate
    )


def test_recorded_baseline_summary_matches_raw_report():
    results = ROOT / "benchmarks/competitive/results"
    report = json.loads((results / "2026-07-27-macos-arm64.json").read_text())

    assert report["git_commit"] == "0612ee509706f74d3ca651b26a88ab6c713d7b1e"
    assert report["configuration"]["node_transport"] == ("@hono/node-server 2.0.12 / HTTP/1.1")
    assert (results / "2026-07-27-macos-arm64.md").read_text() == _render_markdown(report)


def test_current_publication_is_generated_from_raw_evidence():
    competitive_publish.check()


def test_transport_profile_reports_hayate_share_of_raw_ceiling():
    throughput = {
        name: {
            "geometric_mean_requests_per_second": geometric_mean,
            "scenarios": {
                scenario: {"requests_per_second": requests_per_second}
                for scenario, requests_per_second in zip(
                    ("static-text", "dynamic-json", "many-routes-64", "json-echo"),
                    scenario_values,
                    strict=True,
                )
            },
        }
        for name, geometric_mean, scenario_values in (
            ("hayate", 80.0, (80.0, 60.0, 90.0, 70.0)),
            ("raw-asgi", 100.0, (100.0, 100.0, 100.0, 100.0)),
        )
    }

    profile = _transport_profile(throughput)

    assert profile["hayate_efficiency_percent"] == {
        "geometric_mean": 80.0,
        "scenarios": {
            "static-text": 80.0,
            "dynamic-json": 60.0,
            "many-routes-64": 90.0,
            "json-echo": 70.0,
        },
    }
