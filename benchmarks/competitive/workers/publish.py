"""Publish the current native Workers result without hand-copying measurements."""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
import textwrap
import tomllib
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType
from typing import Any

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
MANIFEST_PATH = HERE / "current.toml"
DOC_PATH = ROOT / "docs" / "benchmarks.md"
README_PATH = HERE / "README.md"
START_MARKER = "<!-- workers-current:start -->"
END_MARKER = "<!-- workers-current:end -->"
TARGETS = (
    "hayate",
    "hayate-global",
    "raw-python",
    "raw-js",
    "raw-global",
    "hono",
)
DISPLAY_NAMES = {
    "hayate": "Hayate class",
    "hayate-global": "Hayate global compatibility",
    "raw-python": "Raw Python SDK class",
    "raw-js": "Raw JS objects class",
    "raw-global": "Raw JS objects global",
    "hono": "Hono",
}


class PublicationError(ValueError):
    """Current native Workers evidence or publication is inconsistent."""


@dataclass(frozen=True, slots=True)
class HistoricalResult:
    """One immutable result retained for comparison."""

    label: str
    path: Path


@dataclass(frozen=True, slots=True)
class Publication:
    """The declared current result and historical evidence."""

    current: Path
    historical: tuple[HistoricalResult, ...]


def _load_runner() -> ModuleType:
    name = "_hayate_workers_publication_runner"
    existing = sys.modules.get(name)
    if existing is not None:
        return existing
    path = HERE / "runner.py"
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise PublicationError(f"cannot load {path.relative_to(ROOT)}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


RUNNER = _load_runner()


def _result_path(value: object, *, label: str) -> Path:
    if not isinstance(value, str) or not value:
        raise PublicationError(f"{label} must be a non-empty relative JSON path")
    relative = Path(value)
    if relative.is_absolute() or ".." in relative.parts or relative.suffix != ".json":
        raise PublicationError(f"{label} must be a contained relative JSON path")
    path = HERE / relative
    if path.parent.resolve() != (HERE / "results").resolve() or not path.is_file():
        raise PublicationError(f"{label} does not identify a committed result: {value}")
    return path


def load_publication(path: Path = MANIFEST_PATH) -> Publication:
    """Load and validate the manifest selecting current Workers evidence."""

    data = tomllib.loads(path.read_text(encoding="utf-8"))
    if data.get("schema_version") != 1:
        raise PublicationError("workers/current.toml schema_version must be 1")
    current = _result_path(data.get("result"), label="result")
    raw_historical = data.get("historical")
    if not isinstance(raw_historical, list) or not raw_historical:
        raise PublicationError("workers/current.toml must retain historical results")
    historical: list[HistoricalResult] = []
    seen = {current}
    for index, item in enumerate(raw_historical):
        if not isinstance(item, dict):
            raise PublicationError(f"historical[{index}] must be a table")
        label = item.get("label")
        if not isinstance(label, str) or not label:
            raise PublicationError(f"historical[{index}].label must be non-empty")
        result = _result_path(item.get("result"), label=f"historical[{index}].result")
        if result in seen:
            raise PublicationError(f"duplicate result in workers/current.toml: {result.name}")
        seen.add(result)
        historical.append(HistoricalResult(label, result))
    return Publication(current, tuple(historical))


def _load_report(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise PublicationError(f"{path.name} must contain a JSON object")
    return value


def _paired_markdown(path: Path) -> Path:
    markdown = path.with_suffix(".md")
    if not markdown.is_file():
        raise PublicationError(f"missing rendered result: {markdown.name}")
    return markdown


def _target_result(report: dict[str, Any], name: str) -> dict[str, Any]:
    frameworks = report.get("frameworks")
    if not isinstance(frameworks, dict) or set(frameworks) != set(TARGETS):
        raise PublicationError(f"current Workers report must contain exactly: {', '.join(TARGETS)}")
    result = frameworks[name]
    if not isinstance(result, dict):
        raise PublicationError(f"target result must be an object: {name}")
    return result


def _all_samples(report: dict[str, Any]) -> list[dict[str, Any]]:
    samples: list[dict[str, Any]] = []
    for name in TARGETS:
        throughput = _target_result(report, name).get("throughput")
        if not isinstance(throughput, dict):
            raise PublicationError(f"{name}.throughput must be an object")
        scenarios = throughput.get("scenarios")
        if not isinstance(scenarios, dict) or len(scenarios) != 4:
            raise PublicationError(f"{name} must contain exactly four workloads")
        for scenario in scenarios.values():
            if not isinstance(scenario, dict) or not isinstance(scenario.get("samples"), list):
                raise PublicationError(f"{name} has malformed throughput samples")
            samples.extend(scenario["samples"])
    return samples


def _validate_report(path: Path, report: dict[str, Any]) -> None:
    if report.get("schema_version") != 1:
        raise PublicationError(f"{path.name} schema_version must be 1")
    commit = report.get("git_commit")
    measured_at = report.get("measured_at")
    if not isinstance(commit, str) or len(commit) != 40:
        raise PublicationError(f"{path.name} must record a full Git commit")
    if not isinstance(measured_at, str) or len(measured_at) < 10:
        raise PublicationError(f"{path.name} must record measured_at")
    configuration = report.get("configuration")
    if not isinstance(configuration, dict):
        raise PublicationError(f"{path.name} configuration must be an object")
    if configuration.get("asgi_in_hayate_path") is not False:
        raise PublicationError(f"{path.name} must prove ASGI is absent")
    compatibility_date = configuration.get("compatibility_date")
    if not isinstance(compatibility_date, str) or not compatibility_date:
        raise PublicationError(f"{path.name} must record the compatibility date")
    machine = report.get("machine")
    if not isinstance(machine, dict):
        raise PublicationError(f"{path.name} machine must be an object")
    for key in (
        "node",
        "oha",
        "wrangler",
        "workerd",
        "workers_py",
        "workers_runtime_sdk",
    ):
        if not isinstance(machine.get(key), str) or not machine[key]:
            raise PublicationError(f"{path.name} must record machine.{key}")
    rounds = configuration.get("throughput_rounds")
    if not isinstance(rounds, int) or rounds < 1:
        raise PublicationError(f"{path.name} throughput_rounds must be positive")
    for name in TARGETS:
        result = _target_result(report, name)
        for key in ("payload", "startup", "throughput", "http_contract"):
            if not isinstance(result.get(key), dict):
                raise PublicationError(f"{name}.{key} must be an object")
        contract = result["http_contract"]
        if contract.get("total") != 14:
            raise PublicationError(f"{name} must execute the shared 14-case contract")
        if name != "hono" and contract.get("passed") != 14:
            raise PublicationError(f"{name} must pass the shared HTTP contract")
    samples = _all_samples(report)
    expected_samples = rounds * len(TARGETS) * 4
    if len(samples) != expected_samples:
        raise PublicationError(
            f"{path.name} has {len(samples)} samples; expected {expected_samples}"
        )
    for sample in samples:
        if any(float(sample.get(key, -1)) != 0 for key in ("errors", "timeouts", "non_2xx")):
            raise PublicationError(f"{path.name} contains a failed throughput sample")
    markdown = _paired_markdown(path)
    if markdown.read_text(encoding="utf-8") != RUNNER.render_markdown(report):
        raise PublicationError(f"{markdown.name} does not reproduce from {path.name}")


def validate_current(publication: Publication, report: dict[str, Any]) -> None:
    """Validate current and historical native Workers evidence."""

    _validate_report(publication.current, report)
    configuration = report["configuration"]
    publication_profile = {
        "connections": 20,
        "duration_seconds": 10,
        "throughput_rounds": 3,
        "startup_rounds": 5,
    }
    for key, expected in publication_profile.items():
        if configuration.get(key) != expected:
            raise PublicationError(
                f"current Workers report {key} must be {expected}; found {configuration.get(key)!r}"
            )
    retries = report.get("worker_start_retries")
    if not isinstance(retries, list):
        raise PublicationError("current Workers report must record startup retries")
    for retry in retries:
        if (
            not isinstance(retry, dict)
            or retry.get("target") not in TARGETS
            or retry.get("failed_attempt") != 1
            or not isinstance(retry.get("reason"), str)
        ):
            raise PublicationError("current Workers report has malformed startup retry data")
    for historical in publication.historical:
        _validate_report(historical.path, _load_report(historical.path))


def _paragraph(value: str) -> str:
    return textwrap.fill(
        value,
        width=88,
        break_long_words=False,
        break_on_hyphens=False,
    )


def _result_url(path: Path) -> str:
    relative = path.relative_to(ROOT).as_posix()
    return f"https://github.com/hayatepy/hayate/blob/main/{relative}"


def _rps(result: dict[str, Any]) -> float:
    return float(result["throughput"]["geometric_mean_requests_per_second"])


def _ratio(numerator: int | float, denominator: int | float) -> float:
    return numerator / denominator


def render_current_section(
    publication: Publication,
    report: dict[str, Any],
) -> str:
    """Render the public Workers interpretation directly from raw evidence."""

    validate_current(publication, report)
    measured_date = report["measured_at"][:10]
    commit = report["git_commit"]
    machine = report["machine"]
    configuration = report["configuration"]
    samples = _all_samples(report)
    total_requests = sum(int(sample["requests"]) for sample in samples)
    startup_retries = report["worker_start_retries"]
    hayate = _target_result(report, "hayate")
    hayate_global = _target_result(report, "hayate-global")
    raw_js = _target_result(report, "raw-js")
    raw_global = _target_result(report, "raw-global")
    hono = _target_result(report, "hono")
    hayate_version = hayate["version"]

    lines = [
        f"### Current native Workers baseline (Hayate {hayate_version}, {measured_date})",
        "",
        _paragraph(
            f"{machine['cpu']}, {machine['os']}, {machine['architecture']}, "
            f"CPython {machine['python']}, Node {machine['node'].removeprefix('v')}; "
            f"{configuration['runtime']}; {configuration['connections']} connections, "
            f"{configuration['duration_seconds']} seconds per scenario, "
            f"{configuration['throughput_rounds']} rotating rounds. The source under "
            f"test is commit `{commit[:7]}`. All {len(samples)} throughput samples "
            f"and {total_requests:,} requests completed with zero errors, timeouts, "
            f"or non-2xx responses. Fresh process startup required "
            f"{len(startup_retries)} bounded retries; a second consecutive failure "
            "would have failed the run."
        ),
        "",
        "| Target | Version | Local first response | gzip upload | Throughput | "
        "CPU s / 1k req | Peak tree RSS | HTTP contract |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for name in TARGETS:
        result = _target_result(report, name)
        startup = result["startup"]
        payload = result["payload"]
        throughput = result["throughput"]
        contract = result["http_contract"]
        lines.append(
            f"| {DISPLAY_NAMES[name]} | {result['version']} | "
            f"{startup['local_first_response_ms']:,.1f} ms | "
            f"{payload['upload_gzip_bytes'] / 1_024:,.1f} KiB | "
            f"{throughput['geometric_mean_requests_per_second']:,.0f} req/s | "
            f"{throughput['geometric_mean_cpu_seconds_per_1000_requests']:.4f} | "
            f"{throughput['maximum_median_process_tree_rss_mib']:,.1f} MiB | "
            f"{contract['passed']}/{contract['total']} "
            f"({contract['rate_percent']:.1f}%) |"
        )

    class_efficiency = _ratio(_rps(hayate), _rps(raw_js)) * 100
    global_efficiency = _ratio(_rps(hayate_global), _rps(raw_global)) * 100
    class_hono = _ratio(_rps(hayate), _rps(hono)) * 100
    global_hono = _ratio(_rps(hayate_global), _rps(hono)) * 100
    global_cpu = hayate_global["throughput"]["geometric_mean_cpu_seconds_per_1000_requests"]
    hono_cpu = hono["throughput"]["geometric_mean_cpu_seconds_per_1000_requests"]
    global_rss = hayate_global["throughput"]["maximum_median_process_tree_rss_mib"]
    hono_rss = hono["throughput"]["maximum_median_process_tree_rss_mib"]
    global_payload = hayate_global["payload"]["upload_gzip_bytes"]
    hono_payload = hono["payload"]["upload_gzip_bytes"]
    global_start = hayate_global["startup"]["local_first_response_ms"]
    hono_start = hono["startup"]["local_first_response_ms"]

    lines.extend(
        [
            "",
            _paragraph(
                f"Hayate measured at **{class_efficiency:.2f}%** of the raw class-path "
                f"control and **{global_efficiency:.2f}%** of the raw global-handler "
                "control. This isolates framework overhead from the Python Workers "
                "runtime and entrypoint boundaries on the declared workload."
            ),
            "",
            _paragraph(
                f"Against Hono, Hayate reached **{class_hono:.2f}%** through the "
                f"default class entrypoint and **{global_hono:.2f}%** through the "
                "global-handler compatibility path. The "
                f"{abs(global_hono - 100):.2f}% global-path difference is treated as "
                "shared-host throughput parity, not a hard victory or regression "
                "threshold. Hono remained ahead on resource efficiency: Hayate global "
                f"used {_ratio(global_cpu, hono_cpu):.2f}x "
                f"CPU per request, {_ratio(global_rss, hono_rss):.2f}x peak process-tree "
                f"RSS, {_ratio(global_payload, hono_payload):.2f}x compressed upload, "
                f"and {_ratio(global_start, hono_start):.2f}x local startup time."
            ),
            "",
            _paragraph(
                "ASGI, Uvicorn, and h11 are absent from this profile. The default "
                "Hayate target uses `WorkerEntrypoint.fetch`; the global target uses "
                "`disable_python_no_global_handlers`, which is a compatibility path, "
                "not Cloudflare's current default. Local Wrangler startup is not "
                "deployed edge cold start, raw controls are runtime/FFI boundaries "
                "rather than frameworks, and the 14-case HTTP contract is the declared "
                "workload boundary rather than a universal standards score."
            ),
            "",
            f"- [Raw JSON]({_result_url(publication.current)})",
            f"- [Rendered summary]({_result_url(_paired_markdown(publication.current))})",
            "",
            "Historical evidence remains immutable:",
            "",
            *[
                f"- [{item.label}]({_result_url(_paired_markdown(item.path))})"
                for item in publication.historical
            ],
            "",
            _paragraph(
                "This section is generated from "
                "`benchmarks/competitive/workers/current.toml` and the selected raw "
                "report. Regenerate it with:"
            ),
            "",
            "```sh",
            "uv run python benchmarks/competitive/workers/publish.py",
            "```",
        ]
    )
    return "\n".join(lines)


def _published_document(document: str, section: str) -> str:
    before, separator, remainder = document.partition(START_MARKER)
    if not separator:
        raise PublicationError(f"{DOC_PATH.relative_to(ROOT)} is missing {START_MARKER}")
    _old, separator, after = remainder.partition(END_MARKER)
    if not separator:
        raise PublicationError(f"{DOC_PATH.relative_to(ROOT)} is missing {END_MARKER}")
    return f"{before}{START_MARKER}\n{section}\n{END_MARKER}{after}"


def _validate_readme(publication: Publication) -> None:
    readme = README_PATH.read_text(encoding="utf-8")
    for path in (publication.current, _paired_markdown(publication.current)):
        relative = path.relative_to(HERE).as_posix()
        if f"]({relative})" not in readme:
            raise PublicationError(f"workers/README.md does not link current: {relative}")
    for historical in publication.historical:
        relative = _paired_markdown(historical.path).relative_to(HERE).as_posix()
        if f"]({relative})" not in readme:
            raise PublicationError(
                f"workers/README.md does not retain historical evidence: {relative}"
            )


def expected_document() -> str:
    """Return the complete benchmark page with current Workers evidence."""

    publication = load_publication()
    report = _load_report(publication.current)
    section = render_current_section(publication, report)
    _validate_readme(publication)
    return _published_document(DOC_PATH.read_text(encoding="utf-8"), section)


def check() -> None:
    """Fail when any current Workers publication surface has drifted."""

    document = DOC_PATH.read_text(encoding="utf-8")
    if document != expected_document():
        raise PublicationError(f"{DOC_PATH.relative_to(ROOT)} Workers baseline is stale")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    try:
        if args.check:
            check()
        else:
            DOC_PATH.write_text(expected_document(), encoding="utf-8", newline="\n")
    except PublicationError as error:
        parser.error(str(error))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
