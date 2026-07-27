"""Validate and render the sourced competitive capability matrix."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
DATA_PATH = Path(__file__).with_name("capabilities.json")
OUTPUT_PATH = ROOT / "docs" / "capabilities.md"
FRAMEWORKS = ("hayate", "fastapi", "django", "hono")
COMPETITORS = FRAMEWORKS[1:]
DISPLAY_NAMES = {
    "hayate": "Hayate",
    "fastapi": "FastAPI",
    "django": "Django",
    "hono": "Hono",
}
STATUSES = {
    "core": "Core",
    "first_party": "First-party",
    "platform_adapter": "Platform adapter",
    "external": "External",
    "not_first_party": "No first-party path",
    "not_applicable": "Different scope",
}
COMPARISONS = {
    "advantage": "Hayate advantage",
    "parity": "Parity",
    "competitor_advantage": "Competitor advantage",
    "different_scope": "Different scope",
}
POSITIONS = {
    "advantaged": "Hayate advantaged",
    "competitive": "Competitive / mixed",
    "competitor_advantaged": "Competitor advantaged",
}


class CapabilityDataError(ValueError):
    """The checked capability evidence is malformed."""


def load_data(path: Path = DATA_PATH) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise CapabilityDataError("capability data must be a JSON object")
    return value


def _strings(value: object, label: str) -> list[str]:
    if (
        not isinstance(value, list)
        or not value
        or not all(isinstance(item, str) and item for item in value)
    ):
        raise CapabilityDataError(f"{label} must be a non-empty string list")
    return value


def _validate_source(source: str, *, framework: str, capability_id: str) -> None:
    if source.startswith("https://"):
        return
    if framework != "hayate":
        raise CapabilityDataError(
            f"{capability_id}.{framework} must cite an HTTPS documentation source"
        )
    path = ROOT / source
    if not path.is_file():
        raise CapabilityDataError(f"{capability_id}.hayate evidence does not exist: {source}")


def validate(data: dict[str, Any]) -> None:
    if data.get("schema_version") != 1:
        raise CapabilityDataError("schema_version must be 1")
    if data.get("universal_winner") is not None:
        raise CapabilityDataError("a universal framework winner must not be declared")
    if not isinstance(data.get("as_of"), str):
        raise CapabilityDataError("as_of must be a date string")

    profiles = data.get("profiles")
    capabilities = data.get("capabilities")
    if not isinstance(profiles, list) or not profiles:
        raise CapabilityDataError("profiles must be a non-empty list")
    if not isinstance(capabilities, list) or not capabilities:
        raise CapabilityDataError("capabilities must be a non-empty list")

    profile_ids: set[str] = set()
    profile_members: dict[str, list[str]] = {}
    for profile in profiles:
        if not isinstance(profile, dict):
            raise CapabilityDataError("each profile must be an object")
        profile_id = profile.get("id")
        if not isinstance(profile_id, str) or not profile_id or profile_id in profile_ids:
            raise CapabilityDataError(f"invalid or duplicate profile id: {profile_id!r}")
        profile_ids.add(profile_id)
        if profile.get("position") not in POSITIONS:
            raise CapabilityDataError(f"{profile_id} has an invalid position")
        if not isinstance(profile.get("summary"), str) or not profile["summary"]:
            raise CapabilityDataError(f"{profile_id} needs a summary")
        profile_members[profile_id] = _strings(
            profile.get("capabilities"), f"{profile_id}.capabilities"
        )

    capability_ids: set[str] = set()
    for capability in capabilities:
        if not isinstance(capability, dict):
            raise CapabilityDataError("each capability must be an object")
        capability_id = capability.get("id")
        if (
            not isinstance(capability_id, str)
            or not capability_id
            or capability_id in capability_ids
        ):
            raise CapabilityDataError(f"invalid or duplicate capability id: {capability_id!r}")
        capability_ids.add(capability_id)
        if not isinstance(capability.get("title"), str) or not capability["title"]:
            raise CapabilityDataError(f"{capability_id} needs a title")
        if not isinstance(capability.get("definition"), str) or not capability["definition"]:
            raise CapabilityDataError(f"{capability_id} needs a definition")

        support = capability.get("support")
        if not isinstance(support, dict) or set(support) != set(FRAMEWORKS):
            raise CapabilityDataError(
                f"{capability_id}.support must contain exactly {', '.join(FRAMEWORKS)}"
            )
        for framework in FRAMEWORKS:
            cell = support[framework]
            if not isinstance(cell, dict) or cell.get("status") not in STATUSES:
                raise CapabilityDataError(f"{capability_id}.{framework} has an invalid status")
            if not isinstance(cell.get("note"), str) or not cell["note"]:
                raise CapabilityDataError(f"{capability_id}.{framework} needs a note")
            sources = _strings(cell.get("sources"), f"{capability_id}.{framework}.sources")
            for source in sources:
                _validate_source(source, framework=framework, capability_id=capability_id)
            if (
                framework == "hayate"
                and cell["status"] in {"core", "first_party"}
                and not any(not source.startswith("https://") for source in sources)
            ):
                raise CapabilityDataError(f"{capability_id}.hayate needs checked local evidence")

        comparisons = capability.get("comparisons")
        if not isinstance(comparisons, dict) or set(comparisons) != set(COMPETITORS):
            raise CapabilityDataError(
                f"{capability_id}.comparisons must contain exactly {', '.join(COMPETITORS)}"
            )
        for competitor, comparison in comparisons.items():
            if comparison not in COMPARISONS:
                raise CapabilityDataError(f"{capability_id}.comparisons.{competitor} is invalid")

    for profile_id, members in profile_members.items():
        unknown = sorted(set(members) - capability_ids)
        if unknown:
            raise CapabilityDataError(
                f"{profile_id} references unknown capabilities: {', '.join(unknown)}"
            )

    unprofiled = sorted(
        capability_ids - {member for members in profile_members.values() for member in members}
    )
    if unprofiled:
        raise CapabilityDataError(f"capabilities must belong to a profile: {', '.join(unprofiled)}")


def _source_link(source: str, index: int) -> str:
    if source.startswith("https://"):
        return f"[source {index}]({source})"
    url = f"https://github.com/hayatepy/hayate/blob/main/{source}"
    return f"[evidence {index}]({url})"


def _cell(capability: dict[str, Any], framework: str) -> str:
    cell = capability["support"][framework]
    return f"**{STATUSES[cell['status']]}** — {cell['note']}"


def render(data: dict[str, Any]) -> str:
    validate(data)
    capabilities = {item["id"]: item for item in data["capabilities"]}
    lines = [
        "# Competitive capabilities",
        "",
        f"Evidence reviewed: **{data['as_of']}**.",
        "",
        "This comparison deliberately has **no universal winner and no weighted score**. "
        "Django, FastAPI, Hono, and Hayate optimize for different product shapes. "
        "Each conclusion below names its capability set; support level and evidence "
        "remain visible instead of being collapsed into a marketing percentage.",
        "",
        "Support levels: **Core** is in the framework package; **First-party** is "
        "maintained by the framework organization; **Platform adapter** is an "
        "official deployment-platform path; **External** is a separate community "
        "project; **No first-party path** is not a claim that no community solution "
        "exists; **Different scope** means the capability is not meaningful for that "
        "runtime or product category.",
        "",
        "## Profile verdicts",
        "",
    ]
    for profile in data["profiles"]:
        lines.extend(
            [
                f"### {profile['title']}",
                "",
                f"**{POSITIONS[profile['position']]}** — {profile['summary']}",
                "",
            ]
        )
        for competitor in COMPETITORS:
            counts = Counter(
                capabilities[capability_id]["comparisons"][competitor]
                for capability_id in profile["capabilities"]
            )
            rendered = ", ".join(
                f"{COMPARISONS[key]} {counts[key]}" for key in COMPARISONS if counts[key]
            )
            lines.append(f"- Against {DISPLAY_NAMES[competitor]}: {rendered}.")
        lines.append("")

    lines.extend(
        [
            "## Capability matrix",
            "",
            "| Capability | Hayate | FastAPI | Django | Hono |",
            "|---|---|---|---|---|",
        ]
    )
    for capability in data["capabilities"]:
        lines.append(
            f"| **{capability['title']}**<br>{capability['definition']} "
            f"| {_cell(capability, 'hayate')} "
            f"| {_cell(capability, 'fastapi')} "
            f"| {_cell(capability, 'django')} "
            f"| {_cell(capability, 'hono')} |"
        )

    lines.extend(["", "## Evidence", ""])
    for capability in data["capabilities"]:
        lines.extend([f"### {capability['title']}", ""])
        for framework in FRAMEWORKS:
            cell = capability["support"][framework]
            links = ", ".join(
                _source_link(source, index) for index, source in enumerate(cell["sources"], start=1)
            )
            lines.append(
                f"- **{DISPLAY_NAMES[framework]} — {STATUSES[cell['status']]}:** "
                f"{cell['note']} ({links})"
            )
        comparisons = "; ".join(
            f"{DISPLAY_NAMES[competitor]}: {COMPARISONS[value]}"
            for competitor, value in capability["comparisons"].items()
        )
        lines.extend([f"- **Relative to Hayate:** {comparisons}.", ""])

    lines.extend(
        [
            "## Interpretation guardrails",
            "",
            "- The performance benchmark and its 14-point HTTP contract remain a "
            "same-workload result, not a universal standards or feature score.",
            "- A missing first-party path does not mean that no third-party package "
            "exists. It means adoption requires an independently governed component.",
            "- Ecosystem size, maintainer capacity, long-term stability, and production "
            "track record are adoption factors but are not mislabeled as framework APIs.",
            "- Update the dated source data and regenerate this file when a compared "
            "framework adds or removes a relevant capability.",
            "",
            "Regenerate with:",
            "",
            "```sh",
            "uv run python benchmarks/competitive/capabilities.py",
            "```",
            "",
        ]
    )
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    rendered = render(load_data())
    if args.check:
        if not OUTPUT_PATH.exists() or OUTPUT_PATH.read_text(encoding="utf-8") != rendered:
            parser.error(f"{OUTPUT_PATH.relative_to(ROOT)} is stale")
        return 0
    OUTPUT_PATH.write_text(rendered, encoding="utf-8", newline="\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
