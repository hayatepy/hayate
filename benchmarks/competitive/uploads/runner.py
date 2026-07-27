"""Reproducible multipart upload benchmark for Hayate, FastAPI, Django, and Hono."""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import http.client
import json
import os
import platform
import re
import signal
import socket
import statistics
import subprocess
import sys
import tempfile
import time
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager, suppress
from dataclasses import dataclass
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
COMPETITIVE = HERE.parent
APPS = COMPETITIVE / "apps"
ROOT = HERE.parents[2]
DEFAULT_OUTPUT = ROOT / ".benchmark" / "competitive" / "uploads" / "latest.json"
MIB = 1024 * 1024
BOUNDARY = "hayate-competitive-upload"
PAYLOAD_CHUNK = b"x" * (64 * 1024)


@dataclass(frozen=True, slots=True)
class Framework:
    """One isolated upload benchmark target."""

    name: str
    runtime: str
    directory: Path
    target: str
    distribution: str

    @property
    def python(self) -> Path:
        directory = "Scripts" if os.name == "nt" else "bin"
        executable = "python.exe" if os.name == "nt" else "python"
        return self.directory / ".venv" / directory / executable

    def server_command(self, port: int) -> list[str]:
        if self.runtime == "python":
            return [
                str(self.python),
                "-m",
                "uvicorn",
                self.target,
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
        return ["node", self.target]


FRAMEWORKS = (
    Framework("hayate", "python", APPS / "hayate", "upload_app:app", "hayate"),
    Framework("fastapi", "python", APPS / "fastapi", "upload_app:app", "fastapi"),
    Framework("django", "python", APPS / "django", "upload_app:application", "Django"),
    Framework("hono", "node", APPS / "hono", "upload_app.mjs", "hono"),
)


@dataclass(frozen=True, slots=True)
class Fixture:
    """One deterministic multipart request body."""

    path: Path
    payload_bytes: int
    body_bytes: int
    payload_sha256: str


@dataclass(slots=True)
class ServerRun:
    """Mutable measurements populated when the timed server exits."""

    port: int
    peak_rss_bytes: int = 0


def _run_checked(command: list[str], *, cwd: Path) -> None:
    subprocess.run(
        command,
        cwd=cwd,
        check=True,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )


def setup() -> None:
    """Create isolated environments from the committed locks."""

    for framework in FRAMEWORKS:
        print(f"setup: {framework.name}", flush=True)
        if framework.runtime == "node":
            _run_checked(["npm", "ci", "--omit=dev"], cwd=framework.directory)
            continue
        command = [
            "uv",
            "sync",
            "--project",
            str(framework.directory),
            "--locked",
            "--no-dev",
            "--no-editable",
        ]
        if framework.name == "hayate":
            command.extend(("--reinstall-package", "hayate"))
        if framework.name == "fastapi":
            command.extend(("--extra", "upload"))
        _run_checked(command, cwd=ROOT)


def _fixture(payload_bytes: int) -> Fixture:
    directory = ROOT / ".benchmark" / "competitive" / "uploads" / "fixtures"
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"multipart-{payload_bytes}.bin"
    prefix = (
        f"--{BOUNDARY}\r\n"
        'Content-Disposition: form-data; name="file"; filename="payload.bin"\r\n'
        "Content-Type: application/octet-stream\r\n"
        "\r\n"
    ).encode()
    suffix = f"\r\n--{BOUNDARY}--\r\n".encode()
    expected_size = len(prefix) + payload_bytes + len(suffix)
    if not path.exists() or path.stat().st_size != expected_size:
        with path.open("wb") as output:
            output.write(prefix)
            remaining = payload_bytes
            while remaining:
                chunk = PAYLOAD_CHUNK[:remaining]
                output.write(chunk)
                remaining -= len(chunk)
            output.write(suffix)

    digest = hashlib.sha256()
    remaining = payload_bytes
    while remaining:
        chunk = PAYLOAD_CHUNK[:remaining]
        digest.update(chunk)
        remaining -= len(chunk)
    return Fixture(path, payload_bytes, expected_size, digest.hexdigest())


def _free_port() -> int:
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


def _environment(framework: Framework, port: int) -> dict[str, str]:
    env = dict(os.environ)
    env["BENCH_PORT"] = str(port)
    existing = env.get("PYTHONPATH")
    if framework.runtime == "python":
        env["PYTHONPATH"] = (
            str(framework.directory)
            if not existing
            else os.pathsep.join((str(framework.directory), existing))
        )
    return env


def _health(port: int) -> bool:
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=1)
    try:
        connection.request("GET", "/health")
        response = connection.getresponse()
        return response.status == 200 and response.read() == b"ok"
    finally:
        connection.close()


def _wait_for_http(port: int, process: subprocess.Popen[bytes]) -> None:
    deadline = time.perf_counter() + 20
    while time.perf_counter() < deadline:
        if process.poll() is not None:
            raise RuntimeError(f"server exited with status {process.returncode}")
        try:
            if _health(port):
                return
        except OSError:
            pass
        time.sleep(0.005)
    raise TimeoutError(f"server did not serve health checks on port {port}")


def _child_pid(parent: subprocess.Popen[bytes]) -> int:
    deadline = time.perf_counter() + 5
    while time.perf_counter() < deadline:
        result = subprocess.run(
            ["pgrep", "-P", str(parent.pid)],
            check=False,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
        )
        children = result.stdout.split()
        if children:
            return int(children[0])
        if parent.poll() is not None:
            break
        time.sleep(0.005)
    raise RuntimeError("could not find the server process under /usr/bin/time")


def _time_command(command: list[str]) -> list[str]:
    if sys.platform == "darwin":
        return ["/usr/bin/time", "-l", *command]
    if sys.platform.startswith("linux"):
        return ["/usr/bin/time", "-v", *command]
    raise RuntimeError("upload peak-RSS measurement supports macOS and Linux")


def _parse_peak_rss(output: str) -> int:
    if sys.platform == "darwin":
        match = re.search(r"(\d+)\s+maximum resident set size", output)
        if match is not None:
            return int(match.group(1))
    else:
        match = re.search(r"Maximum resident set size \(kbytes\):\s*(\d+)", output)
        if match is not None:
            return int(match.group(1)) * 1024
    raise RuntimeError(f"/usr/bin/time did not report peak RSS:\n{output}")


def _stop_server(process: subprocess.Popen[bytes], server_pid: int) -> None:
    if process.poll() is not None:
        return
    with suppress(ProcessLookupError):
        os.kill(server_pid, signal.SIGTERM)
    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        with suppress(ProcessLookupError):
            os.kill(server_pid, signal.SIGKILL)
        process.kill()
        process.wait(timeout=5)


@contextmanager
def _running_server(framework: Framework) -> Iterator[ServerRun]:
    port = _free_port()
    measurement = ServerRun(port)
    with tempfile.TemporaryFile() as log:
        process = subprocess.Popen(
            _time_command(framework.server_command(port)),
            cwd=framework.directory,
            env=_environment(framework, port),
            stdout=log,
            stderr=subprocess.STDOUT,
        )
        server_pid = 0
        try:
            server_pid = _child_pid(process)
            _wait_for_http(port, process)
            yield measurement
        except Exception as error:
            log.seek(0)
            output = log.read().decode(errors="replace")
            raise RuntimeError(f"{framework.name} server failed:\n{output}") from error
        finally:
            if server_pid:
                _stop_server(process, server_pid)
            elif process.poll() is None:
                process.kill()
                process.wait(timeout=5)
            log.seek(0)
            output = log.read().decode(errors="replace")
            if process.returncode is not None:
                measurement.peak_rss_bytes = _parse_peak_rss(output)


def _upload_once(port: int, fixture: Fixture) -> dict[str, Any]:
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=180)
    try:
        connection.putrequest("POST", "/upload")
        connection.putheader("content-type", f"multipart/form-data; boundary={BOUNDARY}")
        connection.putheader("content-length", str(fixture.body_bytes))
        connection.endheaders()
        with fixture.path.open("rb") as body:
            while chunk := body.read(64 * 1024):
                connection.send(chunk)
        response = connection.getresponse()
        raw = response.read()
        if response.status != 200:
            raise RuntimeError(f"upload returned {response.status}: {raw.decode(errors='replace')}")
        result: dict[str, Any] = json.loads(raw)
    finally:
        connection.close()
    if result.get("size") != fixture.payload_bytes:
        raise RuntimeError(f"upload size mismatch: {result}")
    if result.get("sha256") != fixture.payload_sha256:
        raise RuntimeError(f"upload digest mismatch: {result}")
    if not isinstance(result.get("temp_disk_bytes"), int):
        raise RuntimeError(f"upload did not report temp_disk_bytes: {result}")
    return result


def _sample(
    framework: Framework,
    fixture: Fixture,
    *,
    requests: int,
    connections: int,
) -> dict[str, Any]:
    with _running_server(framework) as server:
        started = time.perf_counter()
        with ThreadPoolExecutor(max_workers=connections) as executor:
            results = list(
                executor.map(
                    lambda _index: _upload_once(server.port, fixture),
                    range(requests),
                )
            )
        elapsed = time.perf_counter() - started

    temp_disk_values = {int(result["temp_disk_bytes"]) for result in results}
    if len(temp_disk_values) != 1:
        raise RuntimeError(f"{framework.name} reported inconsistent temp storage")
    return {
        "requests": requests,
        "connections": connections,
        "elapsed_seconds": round(elapsed, 6),
        "requests_per_second": round(requests / elapsed, 4),
        "payload_bytes_per_second": round(requests * fixture.payload_bytes / elapsed, 1),
        "peak_rss_bytes": server.peak_rss_bytes,
        "logical_temp_disk_bytes_per_request": temp_disk_values.pop(),
    }


def verify() -> None:
    """Exercise one disk-spilling upload contract on every target."""

    fixture = _fixture(2 * MIB)
    for framework in FRAMEWORKS:
        print(f"verify: {framework.name}", flush=True)
        sample = _sample(framework, fixture, requests=1, connections=1)
        expected_temp = 0 if framework.name == "hono" else fixture.payload_bytes
        if sample["logical_temp_disk_bytes_per_request"] != expected_temp:
            raise RuntimeError(
                f"{framework.name} temp storage mismatch: "
                f"{sample['logical_temp_disk_bytes_per_request']} != {expected_temp}"
            )


def _tool_version(command: list[str]) -> str:
    result = subprocess.run(
        command,
        cwd=ROOT,
        check=True,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    return result.stdout.strip().splitlines()[0]


def _git_commit() -> str:
    return _tool_version(["git", "rev-parse", "HEAD"])


def _lock_sha256(framework: Framework) -> str:
    name = "package-lock.json" if framework.runtime == "node" else "uv.lock"
    return hashlib.sha256((framework.directory / name).read_bytes()).hexdigest()


def _versions(framework: Framework) -> dict[str, str]:
    if framework.runtime == "node":
        lock = json.loads((framework.directory / "package-lock.json").read_text())
        return {
            "@hono/node-server": lock["packages"]["node_modules/@hono/node-server"]["version"],
            "hono": lock["packages"]["node_modules/hono"]["version"],
            "node": _tool_version(["node", "--version"]),
        }
    distributions = {
        "hayate": ("hayate", "uvicorn"),
        "fastapi": ("fastapi", "python-multipart", "uvicorn"),
        "django": ("Django", "uvicorn"),
    }[framework.name]
    script = (
        "import importlib.metadata as m,json,sys;"
        "print(json.dumps({name:m.version(name) for name in sys.argv[1:]}))"
    )
    result = subprocess.run(
        [str(framework.python), "-c", script, *distributions],
        cwd=framework.directory,
        check=True,
        text=True,
        stdout=subprocess.PIPE,
    )
    versions: dict[str, str] = json.loads(result.stdout)
    versions["python"] = _tool_version([str(framework.python), "--version"])
    return versions


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
        "runner_python": platform.python_version(),
        "uv": _tool_version(["uv", "--version"]),
    }


def measure(args: argparse.Namespace) -> dict[str, Any]:
    """Measure both fixed upload sizes with rotating framework order."""

    scenarios = (
        ("1-mib", _fixture(MIB), args.small_requests, args.small_connections),
        ("64-mib", _fixture(64 * MIB), args.large_requests, args.large_connections),
    )
    samples: dict[str, dict[str, list[dict[str, Any]]]] = {
        framework.name: {name: [] for name, *_rest in scenarios} for framework in FRAMEWORKS
    }
    targets = list(FRAMEWORKS)
    for round_index in range(args.rounds):
        order = targets[round_index % len(targets) :] + targets[: round_index % len(targets)]
        scenario_order = (
            scenarios[round_index % len(scenarios) :] + scenarios[: round_index % len(scenarios)]
        )
        for scenario_name, fixture, requests, connections in scenario_order:
            for framework in order:
                print(
                    f"measure: round {round_index + 1}/{args.rounds} "
                    f"{scenario_name} {framework.name}",
                    flush=True,
                )
                samples[framework.name][scenario_name].append(
                    _sample(
                        framework,
                        fixture,
                        requests=requests,
                        connections=connections,
                    )
                )

    report: dict[str, Any] = {
        "schema_version": 1,
        "measured_at": dt.datetime.now(dt.UTC).isoformat(),
        "git_commit": _git_commit(),
        "machine": _machine_metadata(),
        "configuration": {
            "rounds": args.rounds,
            "request_body": "one multipart file part containing deterministic x bytes",
            "read_chunk_bytes": 64 * 1024,
            "native_file_memory_threshold_bytes": MIB,
            "peak_rss": "/usr/bin/time maximum resident set size for a fresh server process",
            "temp_disk": "logical uploaded-file bytes held by disk-backed framework storage",
            "scenarios": {
                name: {
                    "payload_bytes": fixture.payload_bytes,
                    "requests": requests,
                    "connections": connections,
                }
                for name, fixture, requests, connections in scenarios
            },
        },
        "frameworks": {},
    }
    for framework in FRAMEWORKS:
        scenario_results = {}
        for scenario_name, *_rest in scenarios:
            raw = samples[framework.name][scenario_name]
            scenario_results[scenario_name] = {
                "requests_per_second": round(
                    statistics.median(sample["requests_per_second"] for sample in raw),
                    4,
                ),
                "payload_bytes_per_second": round(
                    statistics.median(sample["payload_bytes_per_second"] for sample in raw),
                    1,
                ),
                "peak_rss_bytes": round(
                    statistics.median(sample["peak_rss_bytes"] for sample in raw)
                ),
                "logical_temp_disk_bytes_per_request": round(
                    statistics.median(
                        sample["logical_temp_disk_bytes_per_request"] for sample in raw
                    )
                ),
                "samples": raw,
            }
        report["frameworks"][framework.name] = {
            "versions": _versions(framework),
            "lock_sha256": _lock_sha256(framework),
            "scenarios": scenario_results,
        }
    return report


def render_markdown(report: dict[str, Any]) -> str:
    """Render the compact comparison while JSON retains every sample."""

    lines = [
        "# Competitive multipart upload result",
        "",
        f"- Commit: `{report['git_commit']}`",
        f"- Measured: `{report['measured_at']}`",
        f"- Machine: {report['machine']['cpu']} / {report['machine']['architecture']} / "
        f"{report['machine']['os']}",
        "- Contract: one multipart file, 64 KiB application reads, SHA-256 verification",
        "",
        "| Framework | Size | Requests/s | Payload MiB/s | Peak RSS MiB | "
        "Logical temp MiB/request |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for framework in FRAMEWORKS:
        for scenario_name in ("1-mib", "64-mib"):
            result = report["frameworks"][framework.name]["scenarios"][scenario_name]
            lines.append(
                f"| {framework.name} | {scenario_name} | "
                f"{result['requests_per_second']:,.3f} | "
                f"{result['payload_bytes_per_second'] / MIB:,.1f} | "
                f"{result['peak_rss_bytes'] / MIB:,.1f} | "
                f"{result['logical_temp_disk_bytes_per_request'] / MIB:,.1f} |"
            )
    lines.extend(
        [
            "",
            "Peak RSS is the fresh server process maximum reported by `/usr/bin/time`,",
            "so it includes the framework/runtime baseline and upload handling. Logical",
            "temporary-disk bytes describe the accepted file bytes held by each",
            "framework's disk-backed upload object, not filesystem allocation blocks.",
            "Hono reports zero because its Fetch `FormData` path remains memory-backed;",
            "interpret that together with peak RSS rather than as an isolated win.",
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
    parser.add_argument("--rounds", type=int, default=3)
    parser.add_argument("--small-requests", type=int, default=12)
    parser.add_argument("--small-connections", type=int, default=2)
    parser.add_argument("--large-requests", type=int, default=3)
    parser.add_argument("--large-connections", type=int, default=1)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("setup", help="install all locked isolated environments")
    subparsers.add_parser("verify", help="setup and exercise a 2 MiB disk-spilling upload")
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
        verify()
        return
    if args.command == "all":
        setup()
        verify()
    for name in (
        "rounds",
        "small_requests",
        "small_connections",
        "large_requests",
        "large_connections",
    ):
        if getattr(args, name) < 1:
            raise SystemExit(f"--{name.replace('_', '-')} must be positive")
    _write_report(measure(args), args.output)


if __name__ == "__main__":
    main()
