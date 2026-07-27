"""Reproducible HTTP benchmark for hayate, FastAPI, Django, and Hono.

The benchmark deliberately uses isolated, locked production environments.
Python frameworks share Uvicorn's asyncio + h11 transport; Hono uses its
official Node.js adapter. A checksum-pinned oha binary is the single load
generator for every framework.
"""

from __future__ import annotations

import argparse
import contextlib
import datetime as dt
import hashlib
import http.client
import json
import math
import os
import platform
import socket
import statistics
import subprocess
import sys
import tempfile
import time
import urllib.request
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
APPS = HERE / "apps"
LOAD = HERE / "load"
DEFAULT_OUTPUT = ROOT / ".benchmark" / "competitive" / "latest.json"
JSON_BODY = '{"message":"hello"}'
OHA_VERSION = "1.15.0"
OHA_ASSETS = {
    ("darwin", "arm64"): (
        "oha-macos-arm64",
        "70d7cb7c15ed3d5eb4b7d9a7e76f0a8ee32ba1f18f560acef3b28e8670b89bb0",
    ),
    ("darwin", "x86_64"): (
        "oha-macos-amd64",
        "fc8ccb4126737aae85cc9fbc6f95b161bf8bbb676bf02d4bb6196ec02c709c36",
    ),
    ("linux", "arm64"): (
        "oha-linux-arm64",
        "72d5bf4575cede9f9277f93f097b904f893b0f0cd4d92f0869439b05e1403731",
    ),
    ("linux", "x86_64"): (
        "oha-linux-amd64",
        "86ab7fa2c1df23b3bbc53b73561ffa44a7a38ca08f0e10351df9522a5c4c3c61",
    ),
}


@dataclass(frozen=True, slots=True)
class Framework:
    """One isolated benchmark target."""

    name: str
    runtime: str
    directory: Path
    import_target: str
    server_target: str | None = None
    distribution: str | None = None

    @property
    def python(self) -> Path:
        directory = "Scripts" if os.name == "nt" else "bin"
        executable = "python.exe" if os.name == "nt" else "python"
        return self.directory / ".venv" / directory / executable

    def import_command(self) -> list[str]:
        if self.runtime == "python":
            return [str(self.python), "-c", f"import {self.import_target}"]
        return ["node", "-e", f"import('./{self.import_target}')"]

    def server_command(self, port: int) -> list[str]:
        if self.runtime == "python":
            assert self.server_target is not None
            return [
                str(self.python),
                "-m",
                "uvicorn",
                self.server_target,
                "--host",
                "127.0.0.1",
                "--port",
                str(port),
                "--loop",
                "asyncio",
                "--http",
                "h11",
                "--lifespan",
                "off",
                "--no-access-log",
                "--log-level",
                "warning",
            ]
        return ["node", self.import_target]


FRAMEWORKS = (
    Framework("hayate", "python", APPS / "hayate", "app", "app:app", "hayate"),
    Framework("fastapi", "python", APPS / "fastapi", "app", "app:app", "fastapi"),
    Framework("django", "python", APPS / "django", "app", "app:application", "Django"),
    Framework("hono", "node", APPS / "hono", "app.mjs"),
)
RAW_ASGI = Framework(
    "raw-asgi",
    "python",
    APPS / "hayate",
    "raw_asgi",
    "raw_asgi:app",
)
THROUGHPUT_TARGETS = (*FRAMEWORKS, RAW_ASGI)

SCENARIOS = (
    ("static-text", "GET", "/text", None),
    ("dynamic-json", "GET", "/items/123", None),
    ("many-routes-64", "GET", "/route63/value", None),
    ("json-echo", "POST", "/echo", JSON_BODY),
)

_PYTHON_PAYLOAD_SCRIPT = r"""
import importlib.metadata as metadata
import json
import os
import platform
from pathlib import Path
import zlib

seen = set()
files = []
versions = {}
for distribution in metadata.distributions():
    name = distribution.metadata["Name"]
    versions[name.lower()] = distribution.version
    for item in distribution.files or ():
        path = Path(distribution.locate_file(item))
        try:
            identity = path.resolve()
        except OSError:
            continue
        if identity in seen or not path.is_file():
            continue
        seen.add(identity)
        files.append((f"{name}/{item}", path))

app_path = Path(os.environ["BENCH_APP_PATH"])
files.append(("app.py", app_path))
compressor = zlib.compressobj(level=9, wbits=31)
uncompressed = 0
compressed = 0
for logical_name, path in sorted(files, key=lambda pair: pair[0]):
    data = path.read_bytes()
    uncompressed += len(data)
    compressed += len(compressor.compress(logical_name.encode() + b"\0"))
    compressed += len(compressor.compress(data))
compressed += len(compressor.flush())
print(json.dumps({
    "production_packages": len(versions),
    "production_payload_bytes": uncompressed,
    "production_payload_gzip_bytes": compressed,
    "runtime_version": f"CPython {platform.python_version()}",
    "versions": versions,
}))
"""


def _environment(framework: Framework, port: int | None = None) -> dict[str, str]:
    env = os.environ.copy()
    env.update(
        {
            "BENCH_IMPORT_ONLY": "0",
            "PYTHONDONTWRITEBYTECODE": "1",
            "PYTHONHASHSEED": "0",
            "PYTHONUNBUFFERED": "1",
        }
    )
    if port is not None:
        env["BENCH_PORT"] = str(port)
    return env


def _run_checked(
    command: list[str],
    *,
    cwd: Path,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        cwd=cwd,
        env=env,
        check=True,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )


def setup() -> None:
    """Create every isolated environment from its committed lock file."""

    for framework in FRAMEWORKS:
        print(f"setup: {framework.name}", flush=True)
        if framework.runtime == "python":
            _run_checked(
                [
                    "uv",
                    "sync",
                    "--project",
                    str(framework.directory),
                    "--locked",
                    "--no-dev",
                    "--no-editable",
                ],
                cwd=ROOT,
            )
        else:
            _run_checked(["npm", "ci", "--omit=dev"], cwd=framework.directory)
    print("setup: oha", flush=True)
    _install_oha()


def _oha_executable() -> Path:
    return LOAD / ("oha.exe" if os.name == "nt" else "oha")


def _oha_asset() -> tuple[str, str]:
    machine = platform.machine().lower()
    machine = {"aarch64": "arm64", "amd64": "x86_64"}.get(machine, machine)
    key = (sys.platform, machine)
    try:
        return OHA_ASSETS[key]
    except KeyError as error:
        raise RuntimeError(f"oha {OHA_VERSION} has no pinned asset for {key}") from error


def _install_oha() -> None:
    asset, expected_sha256 = _oha_asset()
    destination = _oha_executable()
    if destination.exists():
        actual_sha256 = hashlib.sha256(destination.read_bytes()).hexdigest()
        if actual_sha256 == expected_sha256:
            return

    url = f"https://github.com/hatoo/oha/releases/download/v{OHA_VERSION}/{asset}"
    request = urllib.request.Request(url, headers={"User-Agent": "hayate-benchmark"})
    with urllib.request.urlopen(request, timeout=60) as response:
        data = response.read()
    actual_sha256 = hashlib.sha256(data).hexdigest()
    if actual_sha256 != expected_sha256:
        raise RuntimeError(
            f"oha checksum mismatch: expected {expected_sha256}, got {actual_sha256}"
        )
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(data)
    destination.chmod(0o755)


def _free_port() -> int:
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


def _request(
    port: int,
    method: str,
    path: str,
    body: str | None = None,
) -> tuple[int, dict[str, str], bytes]:
    headers = {}
    encoded: bytes | None = None
    if body is not None:
        encoded = body.encode()
        headers = {"content-type": "application/json", "content-length": str(len(encoded))}
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=2)
    try:
        connection.request(method, path, body=encoded, headers=headers)
        response = connection.getresponse()
        response_headers = {key.lower(): value for key, value in response.getheaders()}
        return response.status, response_headers, response.read()
    finally:
        connection.close()


def _wait_for_tcp(port: int, process: subprocess.Popen[bytes], deadline: float) -> None:
    while time.perf_counter() < deadline:
        if process.poll() is not None:
            raise RuntimeError(f"server exited with status {process.returncode}")
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.1):
                return
        except OSError:
            time.sleep(0.001)
    raise TimeoutError(f"server did not accept TCP connections on port {port}")


def _wait_for_http(port: int, process: subprocess.Popen[bytes], deadline: float) -> None:
    while time.perf_counter() < deadline:
        if process.poll() is not None:
            raise RuntimeError(f"server exited with status {process.returncode}")
        try:
            status, _, body = _request(port, "GET", "/text")
            if status == 200 and body == b"hello":
                return
        except OSError:
            pass
        time.sleep(0.001)
    raise TimeoutError(f"server did not serve the workload on port {port}")


def _stop_process(process: subprocess.Popen[bytes]) -> None:
    if process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)


@contextlib.contextmanager
def _running_server(framework: Framework) -> Iterator[int]:
    port = _free_port()
    with tempfile.TemporaryFile() as log:
        process = subprocess.Popen(
            framework.server_command(port),
            cwd=framework.directory,
            env=_environment(framework, port),
            stdout=log,
            stderr=subprocess.STDOUT,
        )
        try:
            _wait_for_http(port, process, time.perf_counter() + 15)
            yield port
        except Exception as error:
            log.seek(0)
            output = log.read().decode(errors="replace")
            raise RuntimeError(f"{framework.name} server failed:\n{output}") from error
        finally:
            _stop_process(process)


def _median(values: list[float]) -> float:
    return round(statistics.median(values), 3)


def measure_startup(framework: Framework, rounds: int) -> dict[str, Any]:
    """Measure fresh-process app import and first-response latency."""

    import_samples: list[float] = []
    ready_samples: list[float] = []
    cold_samples: list[float] = []

    # Discard one process to populate OS disk caches consistently.
    import_environment = _environment(framework)
    import_environment["BENCH_IMPORT_ONLY"] = "1"
    _run_checked(
        framework.import_command(),
        cwd=framework.directory,
        env=import_environment,
    )
    for _ in range(rounds):
        env = _environment(framework)
        env["BENCH_IMPORT_ONLY"] = "1"
        started = time.perf_counter()
        _run_checked(framework.import_command(), cwd=framework.directory, env=env)
        import_samples.append((time.perf_counter() - started) * 1_000)

        port = _free_port()
        with tempfile.TemporaryFile() as log:
            started = time.perf_counter()
            process = subprocess.Popen(
                framework.server_command(port),
                cwd=framework.directory,
                env=_environment(framework, port),
                stdout=log,
                stderr=subprocess.STDOUT,
            )
            try:
                _wait_for_tcp(port, process, started + 15)
                ready_samples.append((time.perf_counter() - started) * 1_000)
                _wait_for_http(port, process, started + 15)
                cold_samples.append((time.perf_counter() - started) * 1_000)
            except Exception as error:
                log.seek(0)
                output = log.read().decode(errors="replace")
                raise RuntimeError(f"{framework.name} cold start failed:\n{output}") from error
            finally:
                _stop_process(process)

    return {
        "app_import_ms": _median(import_samples),
        "server_ready_ms": _median(ready_samples),
        "cold_start_ms": _median(cold_samples),
        "samples": {
            "app_import_ms": [round(value, 3) for value in import_samples],
            "server_ready_ms": [round(value, 3) for value in ready_samples],
            "cold_start_ms": [round(value, 3) for value in cold_samples],
        },
    }


def _node_payload(framework: Framework) -> dict[str, Any]:
    lock = json.loads((framework.directory / "package-lock.json").read_text())
    packages: list[tuple[str, Path]] = []
    versions: dict[str, str] = {}
    for relative, details in lock["packages"].items():
        if not relative.startswith("node_modules/") or details.get("dev", False):
            continue
        directory = framework.directory / relative
        if not directory.exists():
            continue
        package_name = relative.removeprefix("node_modules/")
        versions[package_name] = details["version"]
        packages.append((package_name, directory))

    files: list[tuple[str, Path]] = [("app.mjs", framework.directory / "app.mjs")]
    for package_name, directory in packages:
        for path in directory.rglob("*"):
            if path.is_file() and path.name != ".package-lock.json":
                files.append((f"{package_name}/{path.relative_to(directory)}", path))

    import zlib

    compressor = zlib.compressobj(level=9, wbits=31)
    uncompressed = 0
    compressed = 0
    for logical_name, path in sorted(files, key=lambda pair: pair[0]):
        data = path.read_bytes()
        uncompressed += len(data)
        compressed += len(compressor.compress(logical_name.encode() + b"\0"))
        compressed += len(compressor.compress(data))
    compressed += len(compressor.flush())
    return {
        "production_packages": len(versions),
        "production_payload_bytes": uncompressed,
        "production_payload_gzip_bytes": compressed,
        "runtime_version": _tool_version(["node", "--version"]),
        "versions": versions,
    }


def measure_payload(framework: Framework) -> dict[str, Any]:
    """Measure the locked production dependency closure and payload."""

    if framework.runtime == "node":
        payload = _node_payload(framework)
        payload["framework_version"] = payload["versions"]["hono"]
        return payload

    env = _environment(framework)
    env["BENCH_APP_PATH"] = str(framework.directory / "app.py")
    result = subprocess.run(
        [str(framework.python), "-c", _PYTHON_PAYLOAD_SCRIPT],
        cwd=framework.directory,
        env=env,
        check=True,
        text=True,
        stdout=subprocess.PIPE,
    )
    python_payload: dict[str, Any] = json.loads(result.stdout)
    assert framework.distribution is not None
    python_payload["framework_version"] = python_payload["versions"][framework.distribution.lower()]
    return python_payload


def verify_contract(framework: Framework) -> dict[str, Any]:
    """Run a transport-level common HTTP contract against one workload."""

    with _running_server(framework) as port:
        text_status, text_headers, text_body = _request(port, "GET", "/text")
        item_status, _, item_body = _request(port, "GET", "/items/123")
        echo_status, echo_headers, echo_body = _request(port, "POST", "/echo", JSON_BODY)
        missing_status, _, _ = _request(port, "GET", "/missing")
        # Method handling is the assertion here; an unmatched request body
        # would additionally test transport-specific unread-stream disposal.
        wrong_status, wrong_headers, _ = _request(port, "POST", "/text")
        head_status, head_headers, head_body = _request(port, "HEAD", "/text")

    expected_item = {"id": "123", "name": "item-123"}
    expected_echo = {"message": "hello", "length": 5}
    cases = {
        "GET text returns 200": text_status == 200,
        "GET text returns the exact body": text_body == b"hello",
        "GET text has text/plain media type": text_headers.get("content-type", "").startswith(
            "text/plain"
        ),
        "GET path parameter returns 200": item_status == 200,
        "GET path parameter returns exact JSON": json.loads(item_body) == expected_item,
        "POST JSON returns 200": echo_status == 200,
        "POST JSON returns exact JSON": json.loads(echo_body) == expected_echo,
        "POST JSON has application/json media type": echo_headers.get(
            "content-type", ""
        ).startswith("application/json"),
        "unknown route returns 404": missing_status == 404,
        "known route with wrong method returns 405": wrong_status == 405,
        "405 response advertises GET in Allow": "GET" in wrong_headers.get("allow", ""),
        "HEAD has GET status": head_status == text_status,
        "HEAD has no response body": head_body == b"",
        "HEAD preserves GET media type": head_headers.get("content-type")
        == text_headers.get("content-type"),
    }
    passed = sum(cases.values())
    return {
        "passed": passed,
        "total": len(cases),
        "rate_percent": round(passed / len(cases) * 100, 1),
        "cases": cases,
    }


def _oha(
    port: int,
    method: str,
    path: str,
    body: str | None,
    *,
    connections: int,
    duration: int,
) -> dict[str, float]:
    command = [
        str(_oha_executable()),
        "--no-tui",
        "--no-color",
        "--output-format",
        "json",
        "--http-version",
        "1.1",
        "--wait-ongoing-requests-after-deadline",
        "-c",
        str(connections),
        "-z",
        f"{duration}s",
        "-m",
        method,
    ]
    if body is not None:
        command.extend(["-T", "application/json", "-d", body])
    command.append(f"http://127.0.0.1:{port}{path}")
    result = subprocess.run(
        command,
        cwd=LOAD,
        check=True,
        text=True,
        capture_output=True,
        timeout=duration + 30,
    )
    report = json.loads(result.stdout)
    status_codes = report.get("statusCodeDistribution", {})
    errors = report.get("errorDistribution", {})
    non_2xx = sum(count for status, count in status_codes.items() if not 200 <= int(status) < 300)
    return {
        "requests_per_second": float(report["summary"]["requestsPerSec"]),
        "latency_p50_ms": float(report["latencyPercentiles"]["p50"]) * 1_000,
        "latency_p99_ms": float(report["latencyPercentiles"]["p99"]) * 1_000,
        "throughput_bytes_per_second": float(report["summary"]["sizePerSec"]),
        "errors": float(sum(errors.values())),
        "timeouts": float(
            sum(
                count
                for error, count in errors.items()
                if "timeout" in error.lower() or "deadline" in error.lower()
            )
        ),
        "non_2xx": float(non_2xx),
    }


def _geometric_mean(values: list[float]) -> float:
    if not values or any(value <= 0 for value in values):
        return 0.0
    return math.exp(sum(math.log(value) for value in values) / len(values))


def measure_throughput(
    rounds: int,
    duration: int,
    connections: int,
) -> dict[str, dict[str, Any]]:
    """Measure all scenarios with rotating framework order."""

    samples: dict[str, dict[str, list[dict[str, float]]]] = {
        target.name: {scenario[0]: [] for scenario in SCENARIOS} for target in THROUGHPUT_TARGETS
    }
    targets = list(THROUGHPUT_TARGETS)
    for round_index in range(rounds):
        order = targets[round_index % len(targets) :] + targets[: round_index % len(targets)]
        for target in order:
            print(
                f"throughput: round {round_index + 1}/{rounds} {target.name}",
                flush=True,
            )
            with _running_server(target) as port:
                scenarios = list(SCENARIOS)
                offset = round_index % len(scenarios)
                scenarios = scenarios[offset:] + scenarios[:offset]
                for scenario_name, method, path, body in scenarios:
                    for _ in range(25):
                        _request(port, method, path, body)
                    sample = _oha(
                        port,
                        method,
                        path,
                        body,
                        connections=connections,
                        duration=duration,
                    )
                    samples[target.name][scenario_name].append(sample)

    measured: dict[str, dict[str, Any]] = {}
    for target in THROUGHPUT_TARGETS:
        scenarios_result: dict[str, Any] = {}
        scenario_rps: list[float] = []
        for scenario_name, *_ in SCENARIOS:
            scenario_samples = samples[target.name][scenario_name]
            rps = [sample["requests_per_second"] for sample in scenario_samples]
            p50 = [sample["latency_p50_ms"] for sample in scenario_samples]
            p99 = [sample["latency_p99_ms"] for sample in scenario_samples]
            scenario_rps.append(statistics.median(rps))
            scenarios_result[scenario_name] = {
                "requests_per_second": round(statistics.median(rps), 1),
                "latency_p50_ms": round(statistics.median(p50), 3),
                "latency_p99_ms": round(statistics.median(p99), 3),
                "samples": scenario_samples,
            }
        measured[target.name] = {
            "geometric_mean_requests_per_second": round(_geometric_mean(scenario_rps), 1),
            "scenarios": scenarios_result,
        }
    return measured


def _transport_profile(throughput: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """Compare Hayate with a minimal app on its exact Uvicorn/h11 transport."""

    hayate = throughput["hayate"]
    raw = throughput["raw-asgi"]
    efficiency = {
        scenario_name: round(
            hayate["scenarios"][scenario_name]["requests_per_second"]
            / raw["scenarios"][scenario_name]["requests_per_second"]
            * 100,
            1,
        )
        for scenario_name, *_ in SCENARIOS
    }
    return {
        "boundary": "raw ASGI app / same workload / hayate locked Uvicorn environment",
        "raw_asgi": raw,
        "hayate_efficiency_percent": {
            "geometric_mean": round(
                hayate["geometric_mean_requests_per_second"]
                / raw["geometric_mean_requests_per_second"]
                * 100,
                1,
            ),
            "scenarios": efficiency,
        },
    }


def _tool_version(command: list[str]) -> str:
    try:
        result = subprocess.run(
            command,
            cwd=ROOT,
            check=True,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )
    except (OSError, subprocess.CalledProcessError):
        return "unavailable"
    return result.stdout.strip().splitlines()[0]


def _machine_metadata() -> dict[str, Any]:
    cpu = platform.processor() or platform.machine()
    if sys.platform == "darwin":
        result = subprocess.run(
            ["sysctl", "-n", "machdep.cpu.brand_string"],
            check=False,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
        )
        cpu = result.stdout.strip() or cpu
    return {
        "os": platform.platform(),
        "architecture": platform.machine(),
        "cpu": cpu,
        "logical_cpus": os.cpu_count(),
        "python": platform.python_version(),
        "node": _tool_version(["node", "--version"]),
        "npm": _tool_version(["npm", "--version"]),
        "uv": _tool_version(["uv", "--version"]),
        "oha": _tool_version([str(_oha_executable()), "--version"]),
    }


def _locked_node_package_version(package: str) -> str:
    lock = json.loads((APPS / "hono" / "package-lock.json").read_text())
    details = lock["packages"][f"node_modules/{package}"]
    return str(details["version"])


def _git_commit() -> str:
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=ROOT,
        check=True,
        text=True,
        stdout=subprocess.PIPE,
    )
    return result.stdout.strip()


def measure(args: argparse.Namespace) -> dict[str, Any]:
    """Run all metric families and return the raw report."""

    report: dict[str, Any] = {
        "schema_version": 2,
        "measured_at": dt.datetime.now(dt.UTC).isoformat(),
        "git_commit": _git_commit(),
        "machine": _machine_metadata(),
        "configuration": {
            "connections": args.connections,
            "duration_seconds": args.duration,
            "throughput_rounds": args.rounds,
            "cold_start_rounds": args.cold_rounds,
            "load_generator": f"oha {OHA_VERSION} / HTTP/1.1",
            "python_transport": "uvicorn 0.51.0 / asyncio / h11 / lifespan off",
            "node_transport": (
                f"@hono/node-server {_locked_node_package_version('@hono/node-server')} / HTTP/1.1"
            ),
        },
        "frameworks": {},
    }
    for framework in FRAMEWORKS:
        print(f"metadata/startup/contract: {framework.name}", flush=True)
        report["frameworks"][framework.name] = {
            "payload": measure_payload(framework),
            "startup": measure_startup(framework, args.cold_rounds),
            "http_contract": verify_contract(framework),
        }

    throughput = measure_throughput(args.rounds, args.duration, args.connections)
    for framework in FRAMEWORKS:
        report["frameworks"][framework.name]["throughput"] = throughput[framework.name]
    report["python_transport_profile"] = _transport_profile(throughput)
    return report


def _kib(value: int | float) -> str:
    return f"{value / 1024:,.1f}"


def render_markdown(report: dict[str, Any]) -> str:
    """Render the compact human-facing view; raw samples remain in JSON."""

    lines = [
        "# Competitive benchmark result",
        "",
        f"- Commit: `{report['git_commit']}`",
        f"- Measured: `{report['measured_at']}`",
        f"- Machine: {report['machine']['cpu']} / {report['machine']['architecture']} / "
        f"{report['machine']['os']}",
        f"- Load: {report['machine']['oha']}, "
        f"{report['configuration']['connections']} connections, "
        f"{report['configuration']['duration_seconds']}s x "
        f"{report['configuration']['throughput_rounds']} rounds",
        "",
        "| Framework | Version | App import (ms) | Server ready (ms) | "
        "Cold start (ms) | Prod. packages | gzip payload (KiB) | "
        "Throughput geo mean (req/s) | HTTP contract |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for name, result in report["frameworks"].items():
        payload = result["payload"]
        startup = result["startup"]
        contract = result["http_contract"]
        throughput = result["throughput"]
        lines.append(
            f"| {name} | {payload['framework_version']} | "
            f"{startup['app_import_ms']:,.1f} | {startup['server_ready_ms']:,.1f} | "
            f"{startup['cold_start_ms']:,.1f} | {payload['production_packages']} | "
            f"{_kib(payload['production_payload_gzip_bytes'])} | "
            f"{throughput['geometric_mean_requests_per_second']:,.0f} | "
            f"{contract['passed']}/{contract['total']} "
            f"({contract['rate_percent']:.1f}%) |"
        )

    lines.extend(
        [
            "",
            "## Throughput by workload",
            "",
            "| Framework | Static text | Dynamic JSON | 64 routes | JSON echo |",
            "|---|---:|---:|---:|---:|",
        ]
    )
    for name, result in report["frameworks"].items():
        scenarios = result["throughput"]["scenarios"]
        lines.append(
            f"| {name} | {scenarios['static-text']['requests_per_second']:,.0f} | "
            f"{scenarios['dynamic-json']['requests_per_second']:,.0f} | "
            f"{scenarios['many-routes-64']['requests_per_second']:,.0f} | "
            f"{scenarios['json-echo']['requests_per_second']:,.0f} |"
        )

    transport = report["python_transport_profile"]
    raw = transport["raw_asgi"]
    efficiency = transport["hayate_efficiency_percent"]
    lines.extend(
        [
            "",
            "## Python transport profile",
            "",
            "The raw ASGI target runs the same four workloads in hayate's exact",
            "locked Uvicorn/asyncio/h11 environment. It is a transport ceiling,",
            "not a fifth framework or a separately tuned server.",
            "",
            "| Boundary | Geo mean | Static text | Dynamic JSON | 64 routes | JSON echo |",
            "|---|---:|---:|---:|---:|---:|",
            f"| Raw ASGI (req/s) | {raw['geometric_mean_requests_per_second']:,.0f} | "
            f"{raw['scenarios']['static-text']['requests_per_second']:,.0f} | "
            f"{raw['scenarios']['dynamic-json']['requests_per_second']:,.0f} | "
            f"{raw['scenarios']['many-routes-64']['requests_per_second']:,.0f} | "
            f"{raw['scenarios']['json-echo']['requests_per_second']:,.0f} |",
            f"| Hayate / raw efficiency | {efficiency['geometric_mean']:.1f}% | "
            f"{efficiency['scenarios']['static-text']:.1f}% | "
            f"{efficiency['scenarios']['dynamic-json']:.1f}% | "
            f"{efficiency['scenarios']['many-routes-64']:.1f}% | "
            f"{efficiency['scenarios']['json-echo']:.1f}% |",
        ]
    )

    lines.extend(
        [
            "",
            "The HTTP contract is not a universal Web-standards score. It checks the",
            "same observable HTTP behavior for these four workload apps, including",
            "RFC 9110 method handling and HEAD semantics. hayate's WPT results are",
            "reported separately in `docs/conformance.md`.",
            "",
        ]
    )
    return "\n".join(lines)


def _write_report(report: dict[str, Any], output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    markdown = output.with_suffix(".md")
    markdown.write_text(render_markdown(report))
    print(f"raw report: {output}")
    print(f"summary:    {markdown}")


def _add_measure_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--connections", type=int, default=50)
    parser.add_argument("--duration", type=int, default=10)
    parser.add_argument("--rounds", type=int, default=3)
    parser.add_argument("--cold-rounds", type=int, default=7)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("setup", help="install all locked isolated environments")
    subparsers.add_parser("verify", help="setup and run only the common HTTP contract")
    run_parser = subparsers.add_parser("run", help="measure already-installed environments")
    _add_measure_arguments(run_parser)
    all_parser = subparsers.add_parser("all", help="setup, verify, and measure everything")
    _add_measure_arguments(all_parser)
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    if args.command == "setup":
        setup()
        return
    if args.command == "verify":
        setup()
        hayate_failed = False
        for framework in FRAMEWORKS:
            result = verify_contract(framework)
            print(
                f"{framework.name}: {result['passed']}/{result['total']} "
                f"({result['rate_percent']:.1f}%)"
            )
            hayate_failed = hayate_failed or (
                framework.name == "hayate" and result["passed"] != result["total"]
            )
        # Competitive differences are data, not a CI failure. A server or
        # malformed workload response already raises before this point.
        if hayate_failed:
            raise SystemExit("hayate no longer satisfies the common HTTP contract")
        return
    if args.command == "all":
        setup()
    report = measure(args)
    _write_report(report, args.output)


if __name__ == "__main__":
    main()
