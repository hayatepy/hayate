"""The competitive capability report must stay sourced and reproducible."""

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


matrix = _load_module(
    "competitive_capabilities",
    ROOT / "benchmarks/competitive/capabilities.py",
)


def test_checked_capability_data_is_valid_and_rendered():
    data = matrix.load_data()

    matrix.validate(data)

    assert data["universal_winner"] is None
    assert matrix.OUTPUT_PATH.read_text(encoding="utf-8") == matrix.render(data)


def test_hayate_claims_require_local_evidence(tmp_path):
    data = matrix.load_data()
    capability = data["capabilities"][0]
    capability["support"]["hayate"]["sources"] = ["https://github.com/hayatepy/hayate"]

    with pytest.raises(matrix.CapabilityDataError, match="checked local evidence"):
        matrix.validate(data)


def test_competitor_claims_require_documentation_urls():
    data = matrix.load_data()
    capability = data["capabilities"][0]
    capability["support"]["fastapi"]["sources"] = ["README.md"]

    with pytest.raises(matrix.CapabilityDataError, match="HTTPS documentation"):
        matrix.validate(data)


def test_known_losing_profiles_remain_explicit():
    profiles = {profile["id"]: profile for profile in matrix.load_data()["profiles"]}

    assert profiles["traditional_full_stack"]["position"] == "competitor_advantaged"
    assert "Django" in profiles["traditional_full_stack"]["summary"]
    assert profiles["javascript_edge"]["position"] == "competitor_advantaged"
    assert "Hono" in profiles["javascript_edge"]["summary"]
