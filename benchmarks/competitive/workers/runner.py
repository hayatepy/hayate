"""Reproducible native Cloudflare Workers benchmark for Hayate and Hono.

An SDK-only Python control attributes the runtime boundary. All targets run
through the same locked Wrangler/workerd binary and compatibility date.
Hayate enters through ``WorkerEntrypoint.fetch``; ASGI, Uvicorn, and h11 are
not present in this profile.
"""

from __future__ import annotations

import argparse
import contextlib
import datetime as dt
import json
import math
import os
import platform
import shutil
import signal
import statistics
import subprocess
import sys
import tempfile
import time
import tomllib
import zlib
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

COMPETITIVE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(COMPETITIVE))
import runner as http_benchmark  # noqa: E402

HERE = Path(__file__).resolve().parent
ROOT = COMPETITIVE.parents[1]
SOURCE_APPS = HERE / "apps"
TOOLING = HERE / "tooling"
RUNTIME_ROOT = ROOT / ".benchmark" / "competitive" / "workers-runtime"
DEFAULT_OUTPUT = ROOT / ".benchmark" / "competitive" / "workers-latest.json"
COMPATIBILITY_DATE = "2026-07-01"
WRANGLER_VERSION = "4.114.0"
WORKERS_PY_VERSION = "1.15.0"
WORKERS_RUNTIME_SDK_VERSION = "1.6.3"
JSON_BODY = http_benchmark.JSON_BODY
SCENARIOS = http_benchmark.SCENARIOS


@dataclass(frozen=True, slots=True)
class WorkerTarget:
    """One Worker implementation of the shared workload."""

    name: str
    python: bool = False

    @property
    def source(self) -> Path:
        return SOURCE_APPS / self.name

    @property
    def directory(self) -> Path:
        return RUNTIME_ROOT / self.name

    def command(self, port: int, inspector_port: int) -> list[str]:
        return [
            str(_node_executable("wrangler")),
            "dev",
            "--ip",
            "127.0.0.1",
            "--port",
            str(port),
            "--inspector-port",
            str(inspector_port),
            "--local",
            "--no-latest",
            "--log-level",
            "error",
            "--show-interactive-dev-session=false",
        ]


TARGETS = (
    WorkerTarget("hayate", python=True),
    WorkerTarget("raw-python", python=True),
    WorkerTarget("hono"),
)


@dataclass(frozen=True, slots=True)
class RunningWorker:
    port: int
    process: subprocess.Popen[bytes]
    server_ready_ms: float
    first_response_ms: float


@dataclass(frozen=True, slots=True)
class ProcessUsage:
    rss_kib: int
    cpu_seconds: float


def _node_executable(name: str) -> Path:
    suffix = ".cmd" if os.name == "nt" else ""
    return TOOLING / "node_modules" / ".bin" / f"{name}{suffix}"


def _python_executable(name: str) -> Path:
    directory = "Scripts" if os.name == "nt" else "bin"
    suffix = ".exe" if os.name == "nt" else ""
    return TOOLING / ".venv" / directory / f"{name}{suffix}"


def _run_checked(
    command: list[str], *, cwd: Path, env: dict[str, str] | None = None
) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            command,
            cwd=cwd,
            check=True,
            env=env,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )
    except subprocess.CalledProcessError as error:
        rendered = " ".join(command)
        raise RuntimeError(
            f"command failed ({error.returncode}) in {cwd}: {rendered}\n{error.stdout or ''}"
        ) from error


def _replace_local_hayate_dependency(project: Path, wheel: Path) -> None:
    marker = '"hayate==0.0.0"'
    text = project.read_text(encoding="utf-8")
    if text.count(marker) != 1:
        raise RuntimeError(f"expected exactly one {marker} marker in {project}")
    project.write_text(
        text.replace(marker, f'"hayate @ {wheel.resolve().as_uri()}"'),
        encoding="utf-8",
    )


def _require_node_24() -> None:
    version = _run_checked(["node", "--version"], cwd=ROOT).stdout.strip()
    try:
        major = int(version.removeprefix("v").split(".", 1)[0])
    except ValueError as error:
        raise RuntimeError(f"could not parse Node.js version {version!r}") from error
    if major != 24:
        raise RuntimeError(
            f"Node.js 24 is required by the pinned Pyodide launcher; found {version}"
        )


def setup() -> None:
    """Build current Hayate and prepare both immutable Worker fixtures."""

    if os.name == "nt":
        raise RuntimeError("the Workers benchmark currently supports macOS and Linux")

    _require_node_24()
    _run_checked(["npm", "ci", "--ignore-scripts"], cwd=TOOLING)
    _run_checked(
        ["uv", "sync", "--project", str(TOOLING), "--locked", "--no-editable"],
        cwd=ROOT,
    )
    http_benchmark._install_oha()

    if RUNTIME_ROOT.exists():
        shutil.rmtree(RUNTIME_ROOT)
    wheel_dir = RUNTIME_ROOT / "dist"
    wheel_dir.mkdir(parents=True)
    _run_checked(["uv", "build", "--wheel", "--out-dir", str(wheel_dir)], cwd=ROOT)
    wheels = list(wheel_dir.glob("hayate-*.whl"))
    if len(wheels) != 1:
        raise RuntimeError(f"expected one Hayate wheel, found {len(wheels)}")

    for target in TARGETS:
        shutil.copytree(target.source, target.directory)
        (target.directory / "node_modules").symlink_to(
            TOOLING / "node_modules",
            target_is_directory=True,
        )

    hayate_project = next(target for target in TARGETS if target.name == "hayate").directory
    hayate_project /= "pyproject.toml"
    _replace_local_hayate_dependency(hayate_project, wheels[0])
    pywrangler_env = os.environ.copy()
    # setup-uv pins the job's outer interpreter with UV_PYTHON. pywrangler
    # creates and selects its own CPython/Pyodide pair, so inheriting that pin
    # makes uv ignore the valid 3.13 environment and fail on CI.
    pywrangler_env.pop("UV_PYTHON", None)
    for target in TARGETS:
        if target.python:
            _run_checked(
                [
                    str(_python_executable("pywrangler")),
                    "sync",
                    "--force",
                    "--no-allow-build",
                ],
                cwd=target.directory,
                env=pywrangler_env,
            )


def _environment() -> dict[str, str]:
    env = os.environ.copy()
    env.update(
        {
            "CI": "1",
            "NO_COLOR": "1",
            "PYTHONDONTWRITEBYTECODE": "1",
            "WRANGLER_SEND_METRICS": "false",
        }
    )
    return env


def _stop_worker(process: subprocess.Popen[bytes]) -> None:
    if process.poll() is not None:
        return
    try:
        os.killpg(os.getpgid(process.pid), signal.SIGTERM)
    except ProcessLookupError:
        return
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        with contextlib.suppress(ProcessLookupError):
            os.killpg(os.getpgid(process.pid), signal.SIGKILL)
        process.wait(timeout=5)


@contextlib.contextmanager
def _running_worker(target: WorkerTarget) -> Iterator[RunningWorker]:
    port = http_benchmark._free_port()
    inspector_port = http_benchmark._free_port()
    with tempfile.TemporaryFile() as log:
        started = time.perf_counter()
        process = subprocess.Popen(
            target.command(port, inspector_port),
            cwd=target.directory,
            env=_environment(),
            stdout=log,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
        try:
            http_benchmark._wait_for_tcp(port, process, started + 30)
            server_ready_ms = (time.perf_counter() - started) * 1_000
            http_benchmark._wait_for_http(port, process, started + 30)
            first_response_ms = (time.perf_counter() - started) * 1_000
            yield RunningWorker(port, process, server_ready_ms, first_response_ms)
        except Exception as error:
            log.seek(0)
            output = log.read().decode(errors="replace")
            raise RuntimeError(f"{target.name} Worker failed:\n{output}") from error
        finally:
            _stop_worker(process)


def _parse_cpu_time(value: str) -> float:
    days = 0
    if "-" in value:
        day_text, value = value.split("-", 1)
        days = int(day_text)
    parts = value.split(":")
    seconds = float(parts[-1])
    if len(parts) >= 2:
        seconds += int(parts[-2]) * 60
    if len(parts) >= 3:
        seconds += int(parts[-3]) * 3_600
    return days * 86_400 + seconds


def _process_table() -> dict[int, tuple[int, int, float]]:
    if sys.platform.startswith("linux"):
        return _linux_process_table()

    result = subprocess.run(
        ["ps", "-axo", "pid=,ppid=,rss=,time="],
        check=True,
        text=True,
        stdout=subprocess.PIPE,
    )
    processes: dict[int, tuple[int, int, float]] = {}
    for line in result.stdout.splitlines():
        parts = line.split()
        if len(parts) != 4:
            continue
        pid, parent, rss = map(int, parts[:3])
        processes[pid] = (parent, rss, _parse_cpu_time(parts[3]))
    return processes


def _linux_process_table() -> dict[int, tuple[int, int, float]]:
    """Read jiffy-resolution CPU and RSS rather than GNU ps's rounded TIME."""

    ticks = int(os.sysconf("SC_CLK_TCK"))
    page_kib = int(os.sysconf("SC_PAGE_SIZE")) / 1_024
    processes: dict[int, tuple[int, int, float]] = {}
    for directory in Path("/proc").iterdir():
        if not directory.name.isdigit():
            continue
        try:
            stat = (directory / "stat").read_text(encoding="utf-8")
            fields = stat[stat.rfind(")") + 2 :].split()
            parent = int(fields[1])
            cpu_seconds = (int(fields[11]) + int(fields[12])) / ticks
            resident_pages = int((directory / "statm").read_text().split()[1])
        except (FileNotFoundError, IndexError, OSError, ValueError):
            continue
        processes[int(directory.name)] = (
            parent,
            int(resident_pages * page_kib),
            cpu_seconds,
        )
    return processes


def _process_usage(root_pid: int) -> ProcessUsage:
    processes = _process_table()

    descendants = {root_pid}
    changed = True
    while changed:
        changed = False
        for pid, (parent, _, _) in processes.items():
            if parent in descendants and pid not in descendants:
                descendants.add(pid)
                changed = True

    return ProcessUsage(
        rss_kib=sum(processes[pid][1] for pid in descendants if pid in processes),
        cpu_seconds=sum(processes[pid][2] for pid in descendants if pid in processes),
    )


def _ensure_valid_load_sample(
    error_count: int | float,
    non_2xx: int | float,
    distribution: dict[str, Any],
) -> None:
    if error_count or non_2xx:
        raise RuntimeError(
            f"invalid load sample: errors={error_count}, non_2xx={non_2xx}, "
            f"distribution={distribution}"
        )


def _load_sample(
    worker: RunningWorker,
    method: str,
    path: str,
    body: str | None,
    *,
    connections: int,
    duration: int,
) -> dict[str, float]:
    command = [
        str(http_benchmark._oha_executable()),
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
    command.append(f"http://127.0.0.1:{worker.port}{path}")

    before = _process_usage(worker.process.pid)
    peak_rss_kib = before.rss_kib
    load = subprocess.Popen(
        command,
        cwd=http_benchmark.LOAD,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    while load.poll() is None:
        peak_rss_kib = max(peak_rss_kib, _process_usage(worker.process.pid).rss_kib)
        time.sleep(0.02)
    stdout, stderr = load.communicate(timeout=30)
    if load.returncode != 0:
        raise RuntimeError(f"oha failed with status {load.returncode}: {stderr}")
    after = _process_usage(worker.process.pid)
    peak_rss_kib = max(peak_rss_kib, after.rss_kib)

    report = json.loads(stdout)
    status_codes = report.get("statusCodeDistribution", {})
    errors = report.get("errorDistribution", {})
    requests = sum(int(count) for count in status_codes.values())
    non_2xx = sum(count for status, count in status_codes.items() if not 200 <= int(status) < 300)
    error_count = sum(errors.values())
    _ensure_valid_load_sample(error_count, non_2xx, errors)
    cpu_seconds = max(0.0, after.cpu_seconds - before.cpu_seconds)
    return {
        "requests_per_second": float(report["summary"]["requestsPerSec"]),
        "latency_p50_ms": float(report["latencyPercentiles"]["p50"]) * 1_000,
        "latency_p99_ms": float(report["latencyPercentiles"]["p99"]) * 1_000,
        "requests": float(requests),
        "errors": float(error_count),
        "timeouts": float(
            sum(
                count
                for error, count in errors.items()
                if "timeout" in error.lower() or "deadline" in error.lower()
            )
        ),
        "non_2xx": float(non_2xx),
        "worker_cpu_seconds": round(cpu_seconds, 3),
        "worker_cpu_seconds_per_1000_requests": (
            round(cpu_seconds / requests * 1_000, 6) if requests else 0.0
        ),
        "worker_process_tree_peak_rss_mib": round(peak_rss_kib / 1_024, 3),
    }


def _contract_on_port(port: int) -> dict[str, Any]:
    request = http_benchmark._request
    text_status, text_headers, text_body = request(port, "GET", "/text")
    item_status, _, item_body = request(port, "GET", "/items/123")
    echo_status, echo_headers, echo_body = request(port, "POST", "/echo", JSON_BODY)
    missing_status, _, _ = request(port, "GET", "/missing")
    wrong_status, wrong_headers, _ = request(port, "POST", "/text", JSON_BODY)
    head_status, head_headers, head_body = request(port, "HEAD", "/text")
    cases = {
        "GET text returns 200": text_status == 200,
        "GET text returns the exact body": text_body == b"hello",
        "GET text has text/plain media type": text_headers.get("content-type", "").startswith(
            "text/plain"
        ),
        "GET path parameter returns 200": item_status == 200,
        "GET path parameter returns exact JSON": json.loads(item_body)
        == {"id": "123", "name": "item-123"},
        "POST JSON returns 200": echo_status == 200,
        "POST JSON returns exact JSON": json.loads(echo_body) == {"message": "hello", "length": 5},
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


def verify_contract(target: WorkerTarget) -> dict[str, Any]:
    with _running_worker(target) as worker:
        return _contract_on_port(worker.port)


def measure_startup(target: WorkerTarget, rounds: int) -> dict[str, Any]:
    """Measure local Wrangler/workerd process startup, not edge cold start."""

    with _running_worker(target):
        pass
    ready_samples: list[float] = []
    first_response_samples: list[float] = []
    rss_samples: list[float] = []
    for _ in range(rounds):
        with _running_worker(target) as worker:
            ready_samples.append(worker.server_ready_ms)
            first_response_samples.append(worker.first_response_ms)
            rss_samples.append(_process_usage(worker.process.pid).rss_kib / 1_024)
    return {
        "local_server_ready_ms": round(statistics.median(ready_samples), 3),
        "local_first_response_ms": round(statistics.median(first_response_samples), 3),
        "idle_process_tree_rss_mib": round(statistics.median(rss_samples), 3),
        "samples": {
            "local_server_ready_ms": [round(value, 3) for value in ready_samples],
            "local_first_response_ms": [round(value, 3) for value in first_response_samples],
            "idle_process_tree_rss_mib": [round(value, 3) for value in rss_samples],
        },
    }


def _geometric_mean(values: list[float]) -> float:
    if not values or any(value <= 0 for value in values):
        return 0.0
    return math.exp(sum(math.log(value) for value in values) / len(values))


def _sample_median(samples: list[dict[str, float]], key: str) -> float:
    return statistics.median(sample[key] for sample in samples)


def measure_throughput(
    rounds: int,
    duration: int,
    connections: int,
) -> dict[str, dict[str, Any]]:
    samples = {target.name: {scenario[0]: [] for scenario in SCENARIOS} for target in TARGETS}
    targets = list(TARGETS)
    for round_index in range(rounds):
        order = targets[round_index % len(targets) :] + targets[: round_index % len(targets)]
        for target in order:
            print(
                f"workers throughput: round {round_index + 1}/{rounds} {target.name}",
                flush=True,
            )
            scenarios = list(SCENARIOS)
            offset = round_index % len(scenarios)
            scenarios = scenarios[offset:] + scenarios[:offset]
            for scenario_name, method, path, body in scenarios:
                # A fresh process per sample prevents one workload from
                # contaminating the next one's CPU/RSS or Pyodide handle state.
                # Startup is measured separately and is not part of this timer.
                with _running_worker(target) as worker:
                    print(f"workers throughput: {target.name} {scenario_name}", flush=True)
                    for _ in range(25):
                        http_benchmark._request(worker.port, method, path, body)
                    samples[target.name][scenario_name].append(
                        _load_sample(
                            worker,
                            method,
                            path,
                            body,
                            connections=connections,
                            duration=duration,
                        )
                    )

    measured: dict[str, dict[str, Any]] = {}
    for target in TARGETS:
        scenarios_result: dict[str, Any] = {}
        scenario_rps: list[float] = []
        scenario_cpu: list[float] = []
        peak_rss: list[float] = []
        for scenario_name, *_ in SCENARIOS:
            scenario_samples = samples[target.name][scenario_name]
            rps = _sample_median(scenario_samples, "requests_per_second")
            cpu = _sample_median(scenario_samples, "worker_cpu_seconds_per_1000_requests")
            rss = _sample_median(scenario_samples, "worker_process_tree_peak_rss_mib")
            scenario_rps.append(rps)
            scenario_cpu.append(cpu)
            peak_rss.append(rss)
            scenarios_result[scenario_name] = {
                "requests_per_second": round(rps, 1),
                "latency_p50_ms": round(_sample_median(scenario_samples, "latency_p50_ms"), 3),
                "latency_p99_ms": round(_sample_median(scenario_samples, "latency_p99_ms"), 3),
                "worker_cpu_seconds_per_1000_requests": round(cpu, 6),
                "worker_process_tree_peak_rss_mib": round(rss, 3),
                "errors": int(sum(sample["errors"] for sample in scenario_samples)),
                "timeouts": int(sum(sample["timeouts"] for sample in scenario_samples)),
                "non_2xx": int(sum(sample["non_2xx"] for sample in scenario_samples)),
                "samples": scenario_samples,
            }
        measured[target.name] = {
            "geometric_mean_requests_per_second": round(_geometric_mean(scenario_rps), 1),
            "geometric_mean_cpu_seconds_per_1000_requests": round(_geometric_mean(scenario_cpu), 6),
            "maximum_median_process_tree_rss_mib": round(max(peak_rss), 3),
            "scenarios": scenarios_result,
        }
    return measured


def _compressed_directory(directory: Path) -> dict[str, int]:
    files = [path for path in directory.rglob("*") if path.is_file()]
    compressor = zlib.compressobj(level=9, wbits=31)
    uncompressed = 0
    compressed = 0
    for path in sorted(files):
        data = path.read_bytes()
        logical_name = str(path.relative_to(directory))
        uncompressed += len(data)
        compressed += len(compressor.compress(logical_name.encode() + b"\0"))
        compressed += len(compressor.compress(data))
    compressed += len(compressor.flush())
    return {
        "upload_files": len(files),
        "upload_bytes": uncompressed,
        "upload_gzip_bytes": compressed,
    }


def measure_payload(target: WorkerTarget) -> dict[str, Any]:
    output = target.directory / ".benchmark-dist"
    if output.exists():
        shutil.rmtree(output)
    _run_checked(
        [
            str(_node_executable("wrangler")),
            "deploy",
            "--dry-run",
            "--outdir",
            str(output),
            "--minify",
        ],
        cwd=target.directory,
    )
    return _compressed_directory(output)


def _tool_version(command: list[str], *, cwd: Path = ROOT) -> str:
    try:
        result = _run_checked(command, cwd=cwd)
    except (OSError, subprocess.CalledProcessError):
        return "unavailable"
    return result.stdout.strip().splitlines()[0]


def _locked_node_versions() -> dict[str, str]:
    lock = json.loads((TOOLING / "package-lock.json").read_text(encoding="utf-8"))
    packages = lock["packages"]
    return {
        name: packages[f"node_modules/{name}"]["version"]
        for name in ("hono", "wrangler", "workerd")
    }


def _framework_versions() -> dict[str, str]:
    root_project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    return {
        "hayate": root_project["project"]["version"],
        "raw-python": WORKERS_RUNTIME_SDK_VERSION,
        "hono": _locked_node_versions()["hono"],
    }


def _machine_metadata() -> dict[str, Any]:
    return {
        "os": platform.platform(),
        "architecture": platform.machine(),
        "cpu": platform.processor() or platform.machine(),
        "logical_cpus": os.cpu_count(),
        "python": platform.python_version(),
        "node": _tool_version(["node", "--version"]),
        "npm": _tool_version(["npm", "--version"]),
        "uv": _tool_version(["uv", "--version"]),
        "oha": _tool_version([str(http_benchmark._oha_executable()), "--version"]),
        "wrangler": _tool_version([str(_node_executable("wrangler")), "--version"]),
        "workerd": _tool_version([str(_node_executable("workerd")), "--version"]),
        "workers_py": WORKERS_PY_VERSION,
        "workers_runtime_sdk": WORKERS_RUNTIME_SDK_VERSION,
    }


def _git_commit() -> str:
    return _run_checked(["git", "rev-parse", "HEAD"], cwd=ROOT).stdout.strip()


def measure(args: argparse.Namespace) -> dict[str, Any]:
    versions = _framework_versions()
    node_versions = _locked_node_versions()
    report: dict[str, Any] = {
        "schema_version": 1,
        "measured_at": dt.datetime.now(dt.UTC).isoformat(),
        "git_commit": _git_commit(),
        "machine": _machine_metadata(),
        "configuration": {
            "connections": args.connections,
            "duration_seconds": args.duration,
            "throughput_rounds": args.rounds,
            "startup_rounds": args.cold_rounds,
            "compatibility_date": COMPATIBILITY_DATE,
            "runtime": (
                f"Wrangler {WRANGLER_VERSION} / workerd {node_versions['workerd']} "
                "/ local / compatibility-date runtime"
            ),
            "load_generator": f"oha {http_benchmark.OHA_VERSION} / HTTP/1.1",
            "asgi_in_hayate_path": False,
            "startup_scope": (
                "local Wrangler/workerd process start to first response; "
                "not deployed Cloudflare edge cold start"
            ),
            "resource_scope": "Wrangler root process and its descendant process tree",
            "throughput_process_scope": (
                "fresh Worker process per target, scenario, and round; "
                "25 untimed warmup requests before each sample"
            ),
            "valid_sample_requirement": "zero load errors, timeouts, and non-2xx responses",
        },
        "frameworks": {},
    }
    for target in TARGETS:
        print(f"workers metadata/startup/contract: {target.name}", flush=True)
        report["frameworks"][target.name] = {
            "version": versions[target.name],
            "payload": measure_payload(target),
            "startup": measure_startup(target, args.cold_rounds),
            "http_contract": verify_contract(target),
        }
    throughput = measure_throughput(args.rounds, args.duration, args.connections)
    for target in TARGETS:
        report["frameworks"][target.name]["throughput"] = throughput[target.name]
    return report


def _kib(value: int | float) -> str:
    return f"{value / 1_024:,.1f}"


def render_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Native Cloudflare Workers benchmark result",
        "",
        f"- Commit: `{report['git_commit']}`",
        f"- Measured: `{report['measured_at']}`",
        f"- Machine: {report['machine']['cpu']} / {report['machine']['architecture']} / "
        f"{report['machine']['os']}",
        f"- Runtime: {report['configuration']['runtime']}",
        f"- Load: {report['machine']['oha']}, "
        f"{report['configuration']['connections']} connections, "
        f"{report['configuration']['duration_seconds']}s x "
        f"{report['configuration']['throughput_rounds']} rounds",
        "",
        "| Target | Version | Local first response (ms) | Idle tree RSS (MiB) | "
        "Upload gzip (KiB) | Throughput geo mean (req/s) | "
        "CPU s / 1k req | Peak tree RSS (MiB) | HTTP contract |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for name, result in report["frameworks"].items():
        startup = result["startup"]
        payload = result["payload"]
        throughput = result["throughput"]
        contract = result["http_contract"]
        lines.append(
            f"| {name} | {result['version']} | "
            f"{startup['local_first_response_ms']:,.1f} | "
            f"{startup['idle_process_tree_rss_mib']:,.1f} | "
            f"{_kib(payload['upload_gzip_bytes'])} | "
            f"{throughput['geometric_mean_requests_per_second']:,.0f} | "
            f"{throughput['geometric_mean_cpu_seconds_per_1000_requests']:.4f} | "
            f"{throughput['maximum_median_process_tree_rss_mib']:,.1f} | "
            f"{contract['passed']}/{contract['total']} "
            f"({contract['rate_percent']:.1f}%) |"
        )

    lines.extend(
        [
            "",
            "## Throughput by workload",
            "",
            "| Target | Static text | Dynamic JSON | 64 routes | JSON echo |",
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
    lines.extend(
        [
            "",
            "Hayate enters through `WorkerEntrypoint.fetch`; ASGI, Uvicorn, and h11",
            "are absent. Startup is local Wrangler/workerd startup and must not be",
            "reported as deployed Cloudflare edge cold start. RSS and CPU include",
            "Wrangler plus its descendant process tree. Shared-host throughput is",
            "evidence, not a hard regression gate. The raw-python target is the",
            "framework-free Python runtime/SDK boundary, not a framework.",
            "",
        ]
    )
    return "\n".join(lines)


def _write_report(report: dict[str, Any], output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    markdown = output.with_suffix(".md")
    markdown.write_text(render_markdown(report), encoding="utf-8")
    print(f"raw report: {output}")
    print(f"summary:    {markdown}")


def _add_measure_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--connections", type=int, default=20)
    parser.add_argument("--duration", type=int, default=10)
    parser.add_argument("--rounds", type=int, default=3)
    parser.add_argument("--cold-rounds", type=int, default=5)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("setup", help="prepare all locked Worker fixtures")
    subparsers.add_parser("verify", help="setup and run only the common HTTP contract")
    run_parser = subparsers.add_parser("run", help="measure prepared fixtures")
    _add_measure_arguments(run_parser)
    all_parser = subparsers.add_parser("all", help="setup, verify, and measure")
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
        for target in TARGETS:
            result = verify_contract(target)
            print(
                f"{target.name}: {result['passed']}/{result['total']} "
                f"({result['rate_percent']:.1f}%)"
            )
            hayate_failed = hayate_failed or (
                target.name == "hayate" and result["passed"] != result["total"]
            )
        if hayate_failed:
            raise SystemExit("Hayate no longer satisfies the Workers HTTP contract")
        return
    if args.command == "all":
        setup()
    report = measure(args)
    _write_report(report, args.output)


if __name__ == "__main__":
    main()
