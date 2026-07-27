"""Publish the current competitive result without hand-copying measurements."""

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
ROOT = HERE.parents[1]
MANIFEST_PATH = HERE / "current.toml"
DOC_PATH = ROOT / "docs" / "benchmarks.md"
README_PATH = HERE / "README.md"
START_MARKER = "<!-- competitive-current:start -->"
END_MARKER = "<!-- competitive-current:end -->"
FRAMEWORKS = ("hayate", "fastapi", "django", "hono")
DISPLAY_NAMES = {
    "hayate": "Hayate",
    "fastapi": "FastAPI",
    "django": "Django",
    "hono": "Hono",
}


class PublicationError(ValueError):
    """Current benchmark evidence or its publication is inconsistent."""


@dataclass(frozen=True, slots=True)
class HistoricalResult:
    """One immutable result retained for comparison."""

    label: str
    path: Path


@dataclass(frozen=True, slots=True)
class Publication:
    """The declared current result and historical evidence links."""

    current: Path
    historical: tuple[HistoricalResult, ...]


def _load_runner() -> ModuleType:
    name = "_hayate_competitive_publication_runner"
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
    """Load and validate the small manifest that selects current evidence."""

    data = tomllib.loads(path.read_text(encoding="utf-8"))
    if data.get("schema_version") != 1:
        raise PublicationError("current.toml schema_version must be 1")
    current = _result_path(data.get("result"), label="result")
    raw_historical = data.get("historical")
    if not isinstance(raw_historical, list) or not raw_historical:
        raise PublicationError("current.toml must retain historical results")
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
            raise PublicationError(f"duplicate result in current.toml: {result.name}")
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


def _validate_rendered_result(path: Path, report: dict[str, Any]) -> None:
    markdown = _paired_markdown(path)
    expected = RUNNER.render_markdown(report)
    if markdown.read_text(encoding="utf-8") != expected:
        raise PublicationError(f"{markdown.name} does not reproduce from {path.name}")


def _framework_result(report: dict[str, Any], name: str) -> dict[str, Any]:
    frameworks = report.get("frameworks")
    if not isinstance(frameworks, dict) or set(frameworks) != set(FRAMEWORKS):
        raise PublicationError(f"current report must contain exactly {', '.join(FRAMEWORKS)}")
    result = frameworks[name]
    if not isinstance(result, dict):
        raise PublicationError(f"framework result must be an object: {name}")
    return result


def _all_samples(report: dict[str, Any]) -> list[dict[str, Any]]:
    samples: list[dict[str, Any]] = []
    for name in FRAMEWORKS:
        throughput = _framework_result(report, name).get("throughput")
        if not isinstance(throughput, dict):
            raise PublicationError(f"{name}.throughput must be an object")
        scenarios = throughput.get("scenarios")
        if not isinstance(scenarios, dict):
            raise PublicationError(f"{name}.throughput.scenarios must be an object")
        for scenario in scenarios.values():
            if not isinstance(scenario, dict) or not isinstance(scenario.get("samples"), list):
                raise PublicationError(f"{name} has malformed throughput samples")
            samples.extend(scenario["samples"])
    profile = report.get("python_transport_profile")
    if not isinstance(profile, dict):
        raise PublicationError("python_transport_profile must be an object")
    raw = profile.get("raw_asgi")
    if not isinstance(raw, dict) or not isinstance(raw.get("scenarios"), dict):
        raise PublicationError("raw ASGI scenarios are missing")
    for scenario in raw["scenarios"].values():
        if not isinstance(scenario, dict) or not isinstance(scenario.get("samples"), list):
            raise PublicationError("raw ASGI has malformed throughput samples")
        samples.extend(scenario["samples"])
    return samples


def validate_current(publication: Publication, report: dict[str, Any]) -> None:
    """Validate provenance, samples, and every paired immutable rendering."""

    if report.get("schema_version") != 2:
        raise PublicationError("current competitive result schema_version must be 2")
    commit = report.get("git_commit")
    measured_at = report.get("measured_at")
    if not isinstance(commit, str) or len(commit) != 40:
        raise PublicationError("current result must record a full Git commit")
    if not isinstance(measured_at, str) or len(measured_at) < 10:
        raise PublicationError("current result must record measured_at")
    for name in FRAMEWORKS:
        result = _framework_result(report, name)
        for key in ("payload", "startup", "throughput", "http_contract"):
            if not isinstance(result.get(key), dict):
                raise PublicationError(f"{name}.{key} must be an object")

    configuration = report.get("configuration")
    if not isinstance(configuration, dict):
        raise PublicationError("current result configuration must be an object")
    rounds = configuration.get("throughput_rounds")
    if not isinstance(rounds, int) or rounds < 1:
        raise PublicationError("throughput_rounds must be a positive integer")
    samples = _all_samples(report)
    expected_samples = rounds * (len(FRAMEWORKS) + 1) * 4
    if len(samples) != expected_samples:
        raise PublicationError(
            f"current result has {len(samples)} samples; expected {expected_samples}"
        )
    for sample in samples:
        if any(float(sample.get(key, -1)) != 0 for key in ("errors", "timeouts", "non_2xx")):
            raise PublicationError("current result contains a failed throughput sample")

    _validate_rendered_result(publication.current, report)
    for historical in publication.historical:
        _validate_rendered_result(historical.path, _load_report(historical.path))


def _kib(value: int | float) -> str:
    return f"{value / 1024:,.1f}"


def _ratio(numerator: int | float, denominator: int | float) -> str:
    return f"{numerator / denominator:.2f}"


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


def render_current_section(
    publication: Publication,
    report: dict[str, Any],
) -> str:
    """Render the public interpretation directly from one raw report."""

    validate_current(publication, report)
    measured_date = report["measured_at"][:10]
    commit = report["git_commit"]
    machine = report["machine"]
    configuration = report["configuration"]
    hayate = _framework_result(report, "hayate")
    fastapi = _framework_result(report, "fastapi")
    django = _framework_result(report, "django")
    hono = _framework_result(report, "hono")
    hayate_version = hayate["payload"]["framework_version"]
    samples = _all_samples(report)
    os_name = machine["os"]
    if os_name.startswith("macOS-"):
        os_name = f"macOS {os_name.split('-', 2)[1]}"

    lines = [
        f"### Current released baseline (Hayate {hayate_version}, {measured_date})",
        "",
        _paragraph(
            f"{machine['cpu']}, {os_name}, {machine['architecture']}, "
            f"CPython {machine['python']}, Node {machine['node'].removeprefix('v')}; "
            f"{configuration['connections']} connections, "
            f"{configuration['duration_seconds']} seconds per scenario, "
            f"{configuration['throughput_rounds']} rotating rounds. The source under "
            f"test is commit `{commit[:7]}`. All {len(samples)} throughput samples "
            "completed with zero errors, timeouts, or non-2xx responses."
        ),
        "",
        "| Framework | Version | App import | Cold start | Production packages | "
        "gzip payload | Throughput geo mean | HTTP contract |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for name in FRAMEWORKS:
        result = _framework_result(report, name)
        payload = result["payload"]
        startup = result["startup"]
        throughput = result["throughput"]
        contract = result["http_contract"]
        lines.append(
            f"| {DISPLAY_NAMES[name]} | {payload['framework_version']} | "
            f"{startup['app_import_ms']:,.1f} ms | {startup['cold_start_ms']:,.1f} ms | "
            f"{payload['production_packages']} | "
            f"{_kib(payload['production_payload_gzip_bytes'])} KiB | "
            f"{throughput['geometric_mean_requests_per_second']:,.0f} req/s | "
            f"{contract['passed']}/{contract['total']} "
            f"({contract['rate_percent']:.1f}%) |"
        )

    hayate_rps = hayate["throughput"]["geometric_mean_requests_per_second"]
    fastapi_rps = fastapi["throughput"]["geometric_mean_requests_per_second"]
    django_rps = django["throughput"]["geometric_mean_requests_per_second"]
    hono_rps = hono["throughput"]["geometric_mean_requests_per_second"]
    hayate_cold = hayate["startup"]["cold_start_ms"]
    fastapi_cold = fastapi["startup"]["cold_start_ms"]
    django_cold = django["startup"]["cold_start_ms"]
    hono_cold = hono["startup"]["cold_start_ms"]
    hayate_payload = hayate["payload"]["production_payload_gzip_bytes"]
    fastapi_payload = fastapi["payload"]["production_payload_gzip_bytes"]
    django_payload = django["payload"]["production_payload_gzip_bytes"]
    hono_payload = hono["payload"]["production_payload_gzip_bytes"]
    payload_delta = (hayate_payload / hono_payload - 1) * 100
    payload_comparison = "larger" if payload_delta >= 0 else "smaller"
    package_delta = (
        hayate["payload"]["production_packages"] - hono["payload"]["production_packages"]
    )
    package_comparison = "more" if package_delta >= 0 else "fewer"

    lines.extend(
        [
            "",
            _paragraph(
                f"On this workload, Hayate delivered {_ratio(hayate_rps, fastapi_rps)}x "
                f"FastAPI's and {_ratio(hayate_rps, django_rps)}x Django's throughput. "
                f"FastAPI and Django took {_ratio(fastapi_cold, hayate_cold)}x and "
                f"{_ratio(django_cold, hayate_cold)}x as long to cold-start. Hono "
                f"delivered {_ratio(hono_rps, hayate_rps)}x Hayate's throughput, and "
                f"Hayate took {_ratio(hayate_cold, hono_cold)}x as long to cold-start."
            ),
            "",
            _paragraph(
                "Hayate's runtime-excluded compressed payload was "
                f"{abs(payload_delta):.1f}% {payload_comparison} than Hono's official "
                f"Node stack while using {abs(package_delta)} {package_comparison} "
                "production packages. FastAPI's and Django's payloads were "
                f"{_ratio(fastapi_payload, hayate_payload)}x and "
                f"{_ratio(django_payload, hayate_payload)}x Hayate's."
            ),
        ]
    )

    profile = report["python_transport_profile"]
    raw = profile["raw_asgi"]
    efficiency = profile["hayate_efficiency_percent"]
    scenario_efficiencies = list(efficiency["scenarios"].values())
    lines.extend(
        [
            "",
            _paragraph(
                "The same run measured the raw Uvicorn/asyncio/h11 workload ceiling at "
                f"{raw['geometric_mean_requests_per_second']:,.0f} req/s. Hayate "
                f"reached **{efficiency['geometric_mean']:.1f}%** of that ceiling "
                f"overall and {min(scenario_efficiencies):.1f}% to "
                f"{max(scenario_efficiencies):.1f}% across the four workloads. Hono "
                f"was {_ratio(hono_rps, raw['geometric_mean_requests_per_second'])}x "
                "faster than raw Uvicorn itself, so most of the remaining Hono gap "
                "belongs to the runtime/transport boundary rather than Hayate's "
                "framework core."
            ),
            "",
            _paragraph(
                "The full reports contain every sample, latency percentile, resolved "
                "package version, and machine field. These numbers are a reproducible "
                "baseline, not a claim about all applications or hardware."
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
                "`benchmarks/competitive/current.toml` and the selected raw report. "
                "Regenerate it with:"
            ),
            "",
            "```sh",
            "uv run python benchmarks/competitive/publish.py",
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
            raise PublicationError(f"README.md does not link current evidence: {relative}")
    for historical in publication.historical:
        relative = _paired_markdown(historical.path).relative_to(HERE).as_posix()
        if f"]({relative})" not in readme:
            raise PublicationError(f"README.md does not retain historical evidence: {relative}")


def expected_document() -> str:
    """Return the complete public document with current evidence rendered."""

    publication = load_publication()
    report = _load_report(publication.current)
    section = render_current_section(publication, report)
    _validate_readme(publication)
    return _published_document(DOC_PATH.read_text(encoding="utf-8"), section)


def check() -> None:
    """Fail when any current publication surface has drifted."""

    document = DOC_PATH.read_text(encoding="utf-8")
    if document != expected_document():
        raise PublicationError(f"{DOC_PATH.relative_to(ROOT)} current baseline is stale")


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
