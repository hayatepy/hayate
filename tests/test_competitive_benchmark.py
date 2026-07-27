"""Competitive benchmark boundary tests."""

import importlib.util
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
_locked_node_package_version = competitive_runner._locked_node_package_version
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
