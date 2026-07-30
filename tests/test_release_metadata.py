"""Release version metadata must stay synchronized across independent projects."""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
_PUBLIC_VERSION = re.compile(r'^__version__ = "([^"]+)"$', re.MULTILINE)
_PUBLIC_HOME = "https://hayatepy.dev/"
_PUBLIC_COMPATIBILITY = "https://hayatepy.dev/evidence/compatibility/"
_SUPERSEDED_DOCS_PREFIX = "https://github.com/hayatepy/.github/blob/main/docs/"
_SUPERSEDED_PAGES_PREFIX = "https://hayatepy.github.io/"


def _local_hayate_versions(root: Path) -> dict[str, str]:
    versions: dict[str, str] = {}
    for lock_path in sorted(root.rglob("uv.lock")):
        if ".venv" in lock_path.parts:
            continue
        lock = tomllib.loads(lock_path.read_text(encoding="utf-8"))
        for package in lock.get("package", []):
            if package.get("name") != "hayate":
                continue
            source = package.get("source")
            if not isinstance(source, dict):
                continue
            location = source.get("editable", source.get("directory"))
            if not isinstance(location, str):
                continue
            if (lock_path.parent / location).resolve() != root.resolve():
                continue
            versions[str(lock_path.relative_to(root))] = package["version"]
    return versions


def test_release_versions_agree() -> None:
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    expected = project["project"]["version"]

    source = (ROOT / "src/hayate/__init__.py").read_text(encoding="utf-8")
    public_match = _PUBLIC_VERSION.search(source)
    assert public_match is not None, "src/hayate/__init__.py has no __version__"
    assert public_match.group(1) == expected, (
        f"src/hayate/__init__.py has {public_match.group(1)!r}; expected {expected!r}"
    )

    locked = _local_hayate_versions(ROOT)
    assert locked, "no repository lockfile resolves the local Hayate project"
    stale = {path: version for path, version in locked.items() if version != expected}
    assert not stale, f"local Hayate lock versions must be {expected!r}: {stale}"


def test_local_version_discovery_ignores_registry_and_other_packages(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    nested = root / "nested"
    nested.mkdir(parents=True)
    (nested / "uv.lock").write_text(
        """
version = 1

[[package]]
name = "hayate"
version = "99.0.0"
source = { registry = "https://pypi.org/simple" }

[[package]]
name = "not-hayate"
version = "1.2.3"
source = { directory = ".." }

[[package]]
name = "hayate"
version = "1.2.3"
source = { directory = ".." }
""",
        encoding="utf-8",
    )

    assert _local_hayate_versions(root) == {"nested/uv.lock": "1.2.3"}


def test_public_discovery_links_use_the_canonical_site() -> None:
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert project["project"]["urls"]["Homepage"] == _PUBLIC_HOME
    assert project["project"]["urls"]["Documentation"] == _PUBLIC_HOME

    for public_entry_point in ("README.md", "docs/index.md"):
        content = (ROOT / public_entry_point).read_text(encoding="utf-8")
        assert f"[Start here]({_PUBLIC_HOME})" in content
        assert f"[Tested compatibility]({_PUBLIC_COMPATIBILITY})" in content
        assert _SUPERSEDED_DOCS_PREFIX not in content


def test_llms_index_uses_canonical_and_release_immutable_docs() -> None:
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    version = project["project"]["version"]
    content = (ROOT / "docs" / "llms.txt").read_text(encoding="utf-8")

    assert _PUBLIC_HOME in content
    assert "https://hayatepy.dev/get-started/first-app/" in content
    assert "https://hayatepy.dev/deploy/" in content
    assert "https://hayatepy.dev/evidence/benchmarks/" in content
    assert f"https://github.com/hayatepy/hayate/blob/v{version}/docs/" in content
    assert _SUPERSEDED_PAGES_PREFIX not in content
