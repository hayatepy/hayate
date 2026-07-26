"""Native Workers competitive benchmark boundary tests."""

import importlib.util
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


workers_runner = _load_module(
    "workers_competitive_runner",
    ROOT / "benchmarks/competitive/workers/runner.py",
)


def test_cpu_time_parser_accepts_ps_formats():
    parse = workers_runner._parse_cpu_time
    assert parse("0:00.25") == 0.25
    assert parse("1:02.50") == 62.5
    assert parse("2:03:04.50") == 7_384.5
    assert parse("1-02:03:04.50") == 93_784.5


def test_workers_runner_rejects_invalid_high_rps_samples():
    with pytest.raises(RuntimeError, match="errors=3"):
        workers_runner._ensure_valid_load_sample(3, 0, {"connection closed": 3})
    with pytest.raises(RuntimeError, match="non_2xx=1"):
        workers_runner._ensure_valid_load_sample(0, 1, {})


def test_workers_runner_selects_a_reproducible_target_subset():
    targets = workers_runner._select_targets("hayate-global,raw-global,hono")
    assert [target.name for target in targets] == [
        "hayate-global",
        "raw-global",
        "hono",
    ]
    with pytest.raises(SystemExit, match="unknown Workers benchmark target"):
        workers_runner._select_targets("missing")


def test_workers_markdown_keeps_local_startup_boundary_explicit():
    scenario = {
        "requests_per_second": 100.0,
        "latency_p50_ms": 1.0,
        "latency_p99_ms": 2.0,
        "worker_cpu_seconds_per_1000_requests": 0.1,
        "worker_process_tree_peak_rss_mib": 10.0,
        "errors": 0,
        "timeouts": 0,
        "non_2xx": 0,
        "samples": [],
    }
    framework = {
        "version": "1",
        "payload": {"upload_gzip_bytes": 1_024},
        "startup": {
            "local_first_response_ms": 10.0,
            "idle_process_tree_rss_mib": 5.0,
        },
        "http_contract": {"passed": 14, "total": 14, "rate_percent": 100.0},
        "throughput": {
            "geometric_mean_requests_per_second": 100.0,
            "geometric_mean_cpu_seconds_per_1000_requests": 0.1,
            "maximum_median_process_tree_rss_mib": 10.0,
            "scenarios": {
                name: scenario
                for name in ("static-text", "dynamic-json", "many-routes-64", "json-echo")
            },
        },
    }
    report = {
        "git_commit": "abc",
        "measured_at": "now",
        "machine": {"cpu": "cpu", "architecture": "arm64", "os": "os", "oha": "oha"},
        "configuration": {
            "runtime": "workerd",
            "connections": 1,
            "duration_seconds": 1,
            "throughput_rounds": 1,
        },
        "frameworks": {"hayate": framework, "hono": framework},
    }

    markdown = workers_runner.render_markdown(report)

    assert "ASGI, Uvicorn, and h11" in markdown
    assert "must not be" in markdown
    assert "edge cold start" in markdown
