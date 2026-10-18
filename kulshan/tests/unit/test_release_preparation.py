"""Release metadata and supported-runtime contracts."""

from __future__ import annotations

import runpy
import tomllib
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
validate = runpy.run_path(str(ROOT / "scripts/validate_release.py"))["validate"]


def test_python_support_and_optional_mcp_contract() -> None:
    config = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    project = config["project"]
    assert project["requires-python"] == ">=3.11"
    versions = {c.rsplit(" :: ", 1)[-1] for c in project["classifiers"]
                if c.startswith("Programming Language :: Python :: 3.")}
    assert versions == {"3.11", "3.12", "3.13"}
    assert config["tool"]["ruff"]["target-version"] == "py311"
    assert config["tool"]["mypy"]["python_version"] == "3.11"
    assert project["optional-dependencies"]["mcp"] == ["mcp>=1.0,<2"]
    assert not any(d.startswith("tomli>=") for d in project["dependencies"])


def test_prepared_release_metadata_state() -> None:
    version = runpy.run_path(str(ROOT / "src/kulshan/__version__.py"))
    assert version["__version__"] == "0.7.0"
    errors = validate("v0.7.0", ROOT)
    if version["__release_date__"]:
        assert not errors
    else:
        assert any("YYYY-MM-DD" in e for e in errors)
        assert any("no dated" in e for e in errors)


@pytest.mark.parametrize("heading_date,valid", [("2026-01-01", True), ("2026-01-02", False)])
def test_release_dates_must_match(tmp_path: Path, heading_date: str, valid: bool) -> None:
    version_dir = tmp_path / "src/kulshan"
    version_dir.mkdir(parents=True)
    (version_dir / "__version__.py").write_text(
        '__version__ = "0.7.0"\n__release_date__ = "2026-01-01"\n', encoding="utf-8"
    )
    (tmp_path / "CHANGELOG.md").write_text(
        f"## [0.7.0] - {heading_date}\n", encoding="utf-8"
    )
    assert (not validate("v0.7.0", tmp_path)) == valid
