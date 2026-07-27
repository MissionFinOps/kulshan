"""Pinned-source, source-derived inventory, and provenance tests."""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).parents[2]
RESEARCH_ROOT = PROJECT_ROOT / "research" / "upstream" / "aws-cudos"
SCRIPTS_ROOT = PROJECT_ROOT / "scripts" / "research"


def _load_script(name: str):
    sys.path.insert(0, str(SCRIPTS_ROOT))
    try:
        path = SCRIPTS_ROOT / f"{name}.py"
        spec = importlib.util.spec_from_file_location(name, path)
        assert spec and spec.loader
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)
        return module
    finally:
        sys.path.remove(str(SCRIPTS_ROOT))


def test_upstream_manifest_is_complete_and_hash_pinned() -> None:
    manifest = json.loads((RESEARCH_ROOT / "upstream-manifest.json").read_text(encoding="utf-8"))
    sources = {source["source_id"]: source for source in manifest["sources"]}
    assert manifest["retrieval_date"] == "2026-07-26"
    assert (
        sources["aws-cudos-framework"]["pinned_commit"]
        == "f9e36d88c47709f10e8fa784ad11d5cc0e728021"
    )
    assert (
        sources["aws-cudos-data-collection"]["pinned_commit"]
        == "d7945a36c3d9dc166d57752d66edfeb425f44a17"
    )
    assert sources["aws-cudos-framework"]["licence_identifier"] == "MIT-0"
    assert sources["aws-cudos-data-collection"]["licence_identifier"] == "Apache-2.0"
    framework_paths = {item["path"] for item in sources["aws-cudos-framework"]["selected_files"]}
    assert "cid/builtin/core/data/queries/cid/summary_view.sql" in framework_paths
    for source in sources.values():
        assert source["verification_status"] == "verified"
        assert source["licence_source_path"] in {item["path"] for item in source["selected_files"]}
        assert all(
            len(item["git_blob_sha1"]) == 40
            and set(item["git_blob_sha1"]) <= set("0123456789abcdef")
            for item in source["selected_files"]
        )


def _create_git_fixture(tmp_path: Path, files: dict[str, str] | None = None) -> tuple[Path, dict]:
    repository = tmp_path / "upstream"
    repository.mkdir(parents=True)
    subprocess.run(["git", "init", "-q", str(repository)], check=True)
    subprocess.run(
        ["git", "-C", str(repository), "config", "user.email", "test@example.invalid"], check=True
    )
    subprocess.run(["git", "-C", str(repository), "config", "user.name", "Test"], check=True)
    contents = {"LICENSE": "test licence\n", **(files or {})}
    for relative, content in contents.items():
        path = repository / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    subprocess.run(["git", "-C", str(repository), "add", "."], check=True)
    subprocess.run(["git", "-C", str(repository), "commit", "-qm", "fixture"], check=True)
    commit = subprocess.run(
        ["git", "-C", str(repository), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    selected = []
    for relative in contents:
        blob = subprocess.run(
            ["git", "-C", str(repository), "rev-parse", f"{commit}:{relative}"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        selected.append({"path": relative, "git_blob_sha1": blob})
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
        "repository": "example/repo",
        "repository_url": "https://example.invalid/repo.git",
        "pinned_commit": commit,
        "licence_source_path": "LICENSE",
        "selected_files": selected,
        "verification_status": "verified",
    }
    return repository, source


def test_verifier_accepts_exact_commit_and_fails_closed_on_hash_mismatch(tmp_path: Path) -> None:
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
    repository, source = _create_git_fixture(tmp_path / "second")
    source["repository_url"] = "https://example.invalid/wrong.git"
    with pytest.raises(verifier.VerificationError, match="repository URL"):
        verifier.verify_repository(source, repository)


DASHBOARD = """
CalculatedFields:
- DataSetIdentifier: summary_view
  Name: Cost
  Expression: sum({amortized_cost})
- DataSetIdentifier: summary_view
  Name: Cost
  Expression: sum({unblended_cost})
DataSetIdentifierDeclarations:
- Identifier: summary_view
ParameterDeclarations:
- StringParameterDeclaration:
    Name: GroupBy
    DefaultValues: {StaticValues: [service]}
FilterGroups:
- FilterGroupId: service-filter-a
  Filters:
  - CategoryFilter:
      Column: {ColumnName: service, DataSetIdentifier: summary_view}
  ScopeConfiguration: {AllSheets: {}}
- FilterGroupId: service-filter-b
  Filters:
  - CategoryFilter:
      Column: {ColumnName: service, DataSetIdentifier: summary_view}
  ScopeConfiguration: {SelectedSheets: {SheetVisualScopingConfigurations: []}}
Sheets:
- SheetId: summary
  Name: Summary
  FilterControls:
  - Dropdown:
      FilterControlId: service-control
  Visuals:
  - BarChartVisual:
      VisualId: spend-service
      FieldWells: {Values: ['{Cost}'], Category: ['{service}']}
      ColumnHierarchies:
      - ExplicitHierarchy:
          Columns:
          - {ColumnName: service, DataSetIdentifier: summary_view}
          - {ColumnName: account, DataSetIdentifier: summary_view}
          DrillDownFilters: []
  - BarChartVisual:
      VisualId: spend-service-copy
      FieldWells: {Values: ['{Cost}'], Category: ['{service}']}
      ColumnHierarchies:
      - ExplicitHierarchy:
          Columns:
          - {ColumnName: service, DataSetIdentifier: summary_view}
          - {ColumnName: account, DataSetIdentifier: summary_view}
          DrillDownFilters: []
UnsupportedFutureStructure: {value: true}
"""


def _source(extractor, path: Path, relative: str, blob: str = "a" * 40):
    return extractor.SourceFile("fixture", "example/repo", "b" * 40, relative, blob, path)


def test_cudos_shaped_dashboard_inventory_and_semantic_deduplication(tmp_path: Path) -> None:
    extractor = _load_script("extract_aws_cudos_semantics")
    path = tmp_path / "CUDOS-v5-definition.yaml"
    path.write_text(DASHBOARD, encoding="utf-8")
    entities, unsupported = extractor.parse_source(_source(extractor, path, path.name))
    counts = {
        category: sum(item["category"] == category for item in entities)
        for category in {item["category"] for item in entities}
    }
    assert counts["dashboard-sheet"] == 1
    assert counts["dashboard-visual"] == 2
    assert counts["filter-control"] == 1
    assert counts["filter-group"] == 2
    assert counts["parameter"] == 1
    assert counts["drilldown"] == 2
    formulas = [item for item in entities if item["raw_name"] == "Cost"]
    assert len(formulas) == 2
    assert extractor.signature(formulas[0]) != extractor.signature(formulas[1])
    inventory = {
        "schema_version": "1.0",
        "inventory_id": "fixture",
        "entities": entities,
        "unsupported_structures": unsupported,
    }
    catalogue = extractor.build_catalogue(inventory)
    visual_concepts = [
        item for item in catalogue["concepts"] if item["category"] == "dashboard-visual"
    ]
    assert len(visual_concepts) == 1
    assert len(visual_concepts[0]["inventory_ids"]) == 2
    filter_concepts = [item for item in catalogue["concepts"] if item["category"] == "filter-group"]
    assert len(filter_concepts) == 1
    drilldown_concepts = [item for item in catalogue["concepts"] if item["category"] == "drilldown"]
    assert len(drilldown_concepts) == 1
    assert len(drilldown_concepts[0]["inventory_ids"]) == 2
    assert unsupported == [
        {
            "source_file": path.name,
            "source_path": "UnsupportedFutureStructure",
            "reason": "unknown top-level key",
        }
    ]


def test_sql_view_and_embedded_aggregation_are_inventoried(tmp_path: Path) -> None:
    extractor = _load_script("extract_aws_cudos_semantics")
    sql = tmp_path / "summary_view.sql"
    sql.write_text(
        "CREATE OR REPLACE VIEW summary_view AS SELECT charge_type FROM cur;", encoding="utf-8"
    )
    yaml_path = tmp_path / "aggregation.yaml"
    yaml_path.write_text(
        "Resources:\n  Query:\n    Sql: !Sub |\n      SELECT reservation_effective_cost FROM cur\n",
        encoding="utf-8",
    )
    sql_items, _ = extractor.parse_source(_source(extractor, sql, sql.name))
    yaml_items, _ = extractor.parse_source(_source(extractor, yaml_path, yaml_path.name))
    assert sql_items[0]["category"] == "sql-view"
    assert sql_items[0]["raw_name"] == "summary_view"
    assert any(item["category"] == "commitment-calculation" for item in yaml_items)


def test_committed_inventory_is_fully_traceable_to_manifest_and_catalogue() -> None:
    manifest = json.loads((RESEARCH_ROOT / "upstream-manifest.json").read_text(encoding="utf-8"))
    inventory = json.loads((RESEARCH_ROOT / "upstream-inventory.json").read_text(encoding="utf-8"))
    catalogue = json.loads((RESEARCH_ROOT / "semantic-catalogue.json").read_text(encoding="utf-8"))
    pinned = {
        (source["repository"], source["pinned_commit"], item["path"], item["git_blob_sha1"])
        for source in manifest["sources"]
        for item in source["selected_files"]
    }
    inventory_ids = set()
    for item in inventory["entities"]:
        inventory_ids.add(item["inventory_id"])
        assert (
            item["source_repository"],
            item["source_commit"],
            item["source_file"],
            item["source_blob_hash"],
        ) in pinned
    assert inventory_ids
    assert all(
        concept["inventory_ids"] and set(concept["inventory_ids"]) <= inventory_ids
        for concept in catalogue["concepts"]
    )
    assert inventory["unsupported_structures"]
    calculated_categories = {
        "calculated-field",
        "charge-classification",
        "commitment-calculation",
        "comparison-expression",
        "period-expression",
        "recommendation-candidate",
        "service-grouping",
    }
    declared_calculations = [
        item
        for item in inventory["entities"]
        if item["source_file"] == "dashboards/cudos/CUDOS-v5-definition.yaml"
        and item["category"] in calculated_categories
    ]
    assert len(declared_calculations) == 399
    raw_drilldowns = [item for item in inventory["entities"] if item["category"] == "drilldown"]
    semantic_drilldowns = [
        item for item in catalogue["concepts"] if item["category"] == "drilldown"
    ]
    assert len(raw_drilldowns) == 279
    assert len(semantic_drilldowns) == 51
    assert sum(len(item["inventory_ids"]) for item in semantic_drilldowns) == 279
    assert all("hierarchy_type" in item["raw_definition"] for item in raw_drilldowns)
    assert "raw-concepts.json" not in {path.name for path in RESEARCH_ROOT.iterdir()}


def test_regeneration_is_deterministic_and_overwrites_intermediate(tmp_path: Path) -> None:
    extractor = _load_script("extract_aws_cudos_semantics")
    repository, source = _create_git_fixture(
        tmp_path,
        {
            "dashboard.yaml": DASHBOARD,
            "view.sql": "CREATE VIEW summary_view AS SELECT cost FROM cur;\n",
        },
    )
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(
        json.dumps({"schema_version": "1.0", "sources": [source]}), encoding="utf-8"
    )
    outputs = [tmp_path / "inventory.json", tmp_path / "catalogue.json", tmp_path / "report.md"]
    roots = {"fixture": repository}
    extractor.write_outputs(manifest_path, roots, *outputs)
    first = tuple(path.read_bytes() for path in outputs)
    outputs[0].write_text('{"manually_changed": true}', encoding="utf-8")
    extractor.write_outputs(manifest_path, roots, *outputs)
    assert tuple(path.read_bytes() for path in outputs) == first


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
