"""Pinned-source, provenance, and deterministic extraction tests."""

from __future__ import annotations

import importlib.util
import json
import subprocess
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).parents[2]
RESEARCH_ROOT = PROJECT_ROOT / "research" / "upstream" / "aws-cudos"


def _load_script(name: str):
    path = PROJECT_ROOT / "scripts" / "research" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_upstream_manifest_is_complete_and_hash_pinned() -> None:
    manifest = json.loads((RESEARCH_ROOT / "upstream-manifest.json").read_text(encoding="utf-8"))
    sources = {source["source_id"]: source for source in manifest["sources"]}
    assert manifest["retrieval_date"] == "2026-07-26"
    assert sources["aws-cudos-framework"]["pinned_commit"] == (
        "f9e36d88c47709f10e8fa784ad11d5cc0e728021"
    )
    assert sources["aws-cudos-data-collection"]["pinned_commit"] == (
        "d7945a36c3d9dc166d57752d66edfeb425f44a17"
    )
    assert sources["aws-cudos-framework"]["licence_identifier"] == "MIT-0"
    assert sources["aws-cudos-data-collection"]["licence_identifier"] == "Apache-2.0"
    for source in sources.values():
        assert source["verification_status"] == "verified"
        assert source["licence_source_path"] in {item["path"] for item in source["selected_files"]}
        assert all(
            len(item["git_blob_sha1"]) == 40
            and set(item["git_blob_sha1"]) <= set("0123456789abcdef")
            for item in source["selected_files"]
        )


def _create_git_fixture(tmp_path: Path) -> tuple[Path, dict]:
    repository = tmp_path / "upstream"
    repository.mkdir(parents=True)
    subprocess.run(["git", "init", "-q", str(repository)], check=True)
    subprocess.run(
        ["git", "-C", str(repository), "config", "user.email", "test@example.invalid"],
        check=True,
    )
    subprocess.run(["git", "-C", str(repository), "config", "user.name", "Test"], check=True)
    (repository / "LICENSE").write_text("test licence\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(repository), "add", "LICENSE"], check=True)
    subprocess.run(["git", "-C", str(repository), "commit", "-qm", "fixture"], check=True)
    commit = subprocess.run(
        ["git", "-C", str(repository), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    blob = subprocess.run(
        ["git", "-C", str(repository), "rev-parse", f"{commit}:LICENSE"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    subprocess.run(
        [
            "git",
            "-C",
            str(repository),
            "remote",
            "add",
            "origin",
            "https://example.invalid/repo.git",
        ],
        check=True,
    )
    source = {
        "source_id": "fixture",
        "repository_url": "https://example.invalid/repo.git",
        "pinned_commit": commit,
        "licence_source_path": "LICENSE",
        "selected_files": [{"path": "LICENSE", "git_blob_sha1": blob}],
        "verification_status": "verified",
    }
    return repository, source


def test_verifier_accepts_exact_commit_and_fails_closed_on_hash_mismatch(
    tmp_path: Path,
) -> None:
    verifier = _load_script("verify_aws_cudos_upstream")
    repository, source = _create_git_fixture(tmp_path)
    verifier.verify_repository(source, repository)
    source["selected_files"][0]["git_blob_sha1"] = "0" * 40
    with pytest.raises(verifier.VerificationError, match="blob mismatch"):
        verifier.verify_repository(source, repository)


def test_verifier_fails_closed_on_commit_and_repository_mismatch(tmp_path: Path) -> None:
    verifier = _load_script("verify_aws_cudos_upstream")
    repository, source = _create_git_fixture(tmp_path)
    source["pinned_commit"] = "0" * 40
    with pytest.raises(verifier.VerificationError):
        verifier.verify_repository(source, repository)
    _, source = _create_git_fixture(tmp_path / "second")
    source["repository_url"] = "https://example.invalid/wrong.git"
    with pytest.raises(verifier.VerificationError, match="repository URL"):
        verifier.verify_repository(source, tmp_path / "second" / "upstream")


def test_semantic_extraction_is_deduplicated_and_deterministic(tmp_path: Path) -> None:
    extractor = _load_script("extract_aws_cudos_semantics")
    raw = json.loads((RESEARCH_ROOT / "raw-concepts.json").read_text(encoding="utf-8"))
    raw["concepts"].append(dict(raw["concepts"][0]))
    first = extractor.build_catalogue(raw)
    second = extractor.build_catalogue(raw)
    assert first == second
    assert len(first["concepts"]) == len(raw["concepts"]) - 1
    assert len({item["concept_id"] for item in first["concepts"]}) == len(first["concepts"])
    assert all("visual" not in item["concept_id"] for item in first["concepts"])
    catalogue = tmp_path / "catalogue.json"
    report = tmp_path / "report.md"
    extractor.generate(RESEARCH_ROOT / "raw-concepts.json", catalogue, report)
    first_bytes = (catalogue.read_bytes(), report.read_bytes())
    extractor.generate(RESEARCH_ROOT / "raw-concepts.json", catalogue, report)
    assert (catalogue.read_bytes(), report.read_bytes()) == first_bytes


def test_generated_research_files_match_the_generator(tmp_path: Path) -> None:
    extractor = _load_script("extract_aws_cudos_semantics")
    catalogue = tmp_path / "semantic-catalogue.json"
    report = tmp_path / "extraction-report.md"
    extractor.generate(RESEARCH_ROOT / "raw-concepts.json", catalogue, report)
    assert catalogue.read_bytes() == (RESEARCH_ROOT / catalogue.name).read_bytes()
    assert report.read_bytes() == (RESEARCH_ROOT / report.name).read_bytes()


def test_provenance_schema_and_records_do_not_claim_adaptation() -> None:
    schema = json.loads((RESEARCH_ROOT / "provenance-schema.json").read_text(encoding="utf-8"))
    records = json.loads((RESEARCH_ROOT / "provenance-records.json").read_text(encoding="utf-8"))
    assert schema["additionalProperties"] is False
    assert {
        "source_locator",
        "kulshan_destination",
        "kulshan_formula_id",
        "golden_fixture",
        "required_notice",
    } <= set(schema["required"])
    assert records["status"] == "no-upstream-implementation-adopted"
    assert records["records"] == []
