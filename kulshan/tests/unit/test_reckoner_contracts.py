"""Behavioral tests for foundational Reckoner contracts."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from kulshan.reckoner.contracts import (
    MAX_RESULT_LIMIT,
    ColumnDefinition,
    ComparisonKind,
    ComparisonSpec,
    ExecutionSource,
    FilterOperator,
    FilterSpec,
    OutputFormat,
    PeriodSpec,
    PlannerDecision,
    PlannerReason,
    ProvenanceRecord,
    QueryResult,
    QuerySpec,
    ReckonerContractError,
    ResolvedRange,
    SortDirection,
    SortSpec,
    SourceManifestRef,
    TrustInspection,
    Visualization,
)
from kulshan.reckoner.modules import MODULE_SCHEMA_VERSION, ModuleDefinition, load_module
from kulshan.reckoner.registries import (
    DIMENSION_IDS,
    METRIC_IDS,
    METRICS,
    PERIOD_IDS,
    ImplementationStatus,
    resolve_dimension,
    validate_filter_operator,
)

FIXTURES = Path(__file__).parents[1] / "fixtures" / "reckoner"


def _query() -> QuerySpec:
    return QuerySpec(
        metric="unblended-cost",
        period=PeriodSpec("previous-complete-month"),
        groupings=("service", "account"),
        filters=(FilterSpec("region", FilterOperator.IN, ("us-east-1",)),),
        exclusions=(FilterSpec("charge-type", FilterOperator.EQUALS, ("Tax",)),),
        comparison=ComparisonSpec(ComparisonKind.PREVIOUS_PERIOD),
        sort=(SortSpec("unblended-cost", SortDirection.DESCENDING),),
        limit=50,
        visualization=Visualization.TABLE,
        execution_source=ExecutionSource.AUTO,
        output_format=OutputFormat.JSON,
    )


def test_query_spec_round_trip_is_machine_stable() -> None:
    query = _query()
    serialized = json.loads(json.dumps(query.to_dict(), sort_keys=True))
    restored = QuerySpec.from_dict(serialized)
    assert restored == query
    assert restored.to_dict() == serialized
    forbidden = {"sql", "python", "credentials", "session", "rows", "hooks"}
    assert forbidden.isdisjoint(serialized)


@pytest.mark.parametrize(
    ("change", "message"),
    [
        ({"schema_version": "2.0"}, "schema_version"),
        ({"metric": ""}, "metric"),
        ({"groupings": ["service", "account", "region", "resource"]}, "three"),
        ({"groupings": ["service", "service"]}, "duplicate"),
        ({"limit": 0}, "limit"),
        ({"limit": MAX_RESULT_LIMIT + 1}, "limit"),
        ({"execution_source": "athena"}, "execution_source"),
        ({"output_format": "parquet"}, "output_format"),
    ],
)
def test_query_spec_rejects_invalid_contracts(change: dict, message: str) -> None:
    payload = _query().to_dict()
    payload.update(change)
    with pytest.raises(ReckonerContractError, match=message):
        QuerySpec.from_dict(payload)


def test_saved_query_rejects_unknown_fields_and_executable_content() -> None:
    payload = _query().to_dict()
    payload["sql"] = "select * from customer_data"
    with pytest.raises(ReckonerContractError, match="unknown fields"):
        QuerySpec.from_dict(payload)


@pytest.mark.parametrize(
    ("operator", "values", "valid"),
    [
        ("in", [], False),
        ("not-in", [], False),
        ("between", [1], False),
        ("between", [1, 2], True),
        ("is-null", ["x"], False),
        ("is-null", [], True),
        ("equals", ["x", "y"], False),
    ],
)
def test_filter_operator_value_contract(operator: str, values: list, valid: bool) -> None:
    payload = {"dimension": "service", "operator": operator, "values": values}
    if valid:
        assert FilterSpec.from_dict(payload).operator.value == operator
    else:
        with pytest.raises(ReckonerContractError):
            FilterSpec.from_dict(payload)


def test_custom_period_is_half_open_and_comparison_is_shaped() -> None:
    period = PeriodSpec("custom", "2026-01-01", "2026-02-01")
    comparison = ComparisonSpec(
        ComparisonKind.CUSTOM, PeriodSpec("custom", "2025-12-01", "2026-01-01")
    )
    assert period.to_dict()["range_rule"] == "start <= usage_time < end"
    assert comparison.to_dict()["period"]["end"] == "2026-01-01"
    with pytest.raises(ReckonerContractError):
        PeriodSpec("custom", "2026-02-01", "2026-01-01")
    with pytest.raises(ReckonerContractError):
        ComparisonSpec(ComparisonKind.CUSTOM)


def test_query_result_round_trip_preserves_execution_and_trust_fields() -> None:
    result = QueryResult(
        query=_query(),
        period=ResolvedRange("2026-06-01", "2026-07-01"),
        comparison_period=ResolvedRange("2026-05-01", "2026-06-01"),
        columns=(ColumnDefinition("service", "Service", "string"),),
        rows=({"service": "Amazon EC2", "unblended-cost": 42.0},),
        totals={"unblended-cost": 42.0},
        comparison_totals={"unblended-cost": 30.0},
        deltas={"unblended-cost": 12.0},
        new_groups=({"service": "Amazon EC2"},),
        cost_basis={"metric": "unblended-cost"},
        source_manifests=(SourceManifestRef("cur", "s3://redacted", "sha256:abc", redacted=True),),
        execution_source=ExecutionSource.LOCAL,
        cache_partitions=("2026-06",),
        freshness={"data_through": "2026-06-30"},
        provisional=False,
        limitations=("No invoice reconciliation in PR 0 fixture.",),
        generated_sql="SELECT placeholder",
        bindings={"start": "2026-06-01"},
        rows_scanned=10,
        rows_returned=1,
        s3_bytes_read=0,
        execution_duration_ms=5,
        display_metadata={"title": "Contract fixture"},
    )
    payload = json.loads(json.dumps(result.to_dict(), sort_keys=True))
    assert QueryResult.from_dict(payload) == result
    assert payload["source_manifests"][0]["redacted"] is True
    assert payload["rows_returned"] == len(payload["rows"])


def test_query_result_rejects_unknown_fields_and_inconsistent_counts() -> None:
    payload = QueryResult(
        query=_query(),
        period=ResolvedRange("2026-06-01", "2026-07-01"),
        execution_source=ExecutionSource.CACHE,
    ).to_dict()
    payload["future"] = True
    with pytest.raises(ReckonerContractError, match="unknown fields"):
        QueryResult.from_dict(payload)
    payload.pop("future")
    payload["rows_returned"] = 1
    with pytest.raises(ReckonerContractError, match="row count"):
        QueryResult.from_dict(payload)


def test_registry_vocabulary_and_status_are_stable() -> None:
    assert METRIC_IDS == (
        "invoiced-cost",
        "net-unblended-cost",
        "unblended-cost",
        "blended-cost",
        "amortized-cost",
        "net-amortized-cost",
        "effective-cost",
        "public-on-demand-cost",
        "credits",
        "refunds",
        "support",
        "taxes",
        "savings-plan-fees",
        "reserved-instance-fees",
        "unused-commitment-cost",
        "usage-quantity",
    )
    assert set(PERIOD_IDS) == {
        "current-billing-period",
        "previous-complete-month",
        "last-7-days",
        "last-30-days",
        "last-3-complete-months",
        "last-6-complete-months",
        "last-12-complete-months",
        "last-13-billing-periods",
        "last-18-billing-periods",
        "year-to-date",
        "previous-year-to-date",
        "custom",
    }
    assert set(DIMENSION_IDS) >= {"service", "account", "resource", "commitment"}
    assert all(
        descriptor.implementation_status is ImplementationStatus.PLANNED
        and descriptor.formula_version is None
        for descriptor in (METRICS[metric_id] for metric_id in METRIC_IDS)
    )
    assert METRICS["auto"].implementation_status is ImplementationStatus.COMPATIBILITY_ONLY


def test_dynamic_dimension_keys_are_validated_and_operator_scoped() -> None:
    tag = resolve_dimension("tag:owner.team")
    category = resolve_dimension("cost-category:BusinessUnit")
    assert tag.sensitivity == category.sensitivity == "customer-defined"
    validate_filter_operator("tag:owner.team", FilterOperator.CONTAINS)
    with pytest.raises(ReckonerContractError):
        resolve_dimension("tag:")
    with pytest.raises(ReckonerContractError):
        resolve_dimension("cost-category:bad key")
    with pytest.raises(ReckonerContractError):
        validate_filter_operator("tag:owner", FilterOperator.BETWEEN)


def test_planner_decision_explains_satisfied_and_unsatisfied_selection() -> None:
    selected = PlannerDecision(
        selected_source=ExecutionSource.S3,
        reason=PlannerReason.S3_REQUIRED,
        s3_estimate_required=True,
        confirmation_required=True,
    )
    assert selected.to_dict()["confirmation_required"] is True
    blocked = PlannerDecision(
        selected_source=None,
        reason=PlannerReason.UNSATISFIED,
        unsatisfied_requirement="No source covers resource dimension.",
    )
    assert blocked.to_dict()["selected_source"] is None
    with pytest.raises(ReckonerContractError):
        PlannerDecision(selected_source=None, reason=PlannerReason.UNSATISFIED)


def test_trust_inspection_keeps_sql_and_bindings_separate() -> None:
    trust = TrustInspection(
        metric="unblended-cost",
        cost_basis={"currency": "USD"},
        formula_id=None,
        formula_version=None,
        period=ResolvedRange("2026-06-01", "2026-07-01"),
        comparison_period=None,
        groupings=("service",),
        filters=(),
        exclusions=(),
        execution_source=ExecutionSource.S3,
        cache_coverage=None,
        freshness={"provisional": True},
        limitations=("Formula not implemented.",),
        generated_sql="SELECT cost WHERE usage_time >= ?",
        bindings={"start": "2026-06-01"},
        source_manifests=(SourceManifestRef("cur", redacted=True),),
        schema_fingerprints=("sha256:abc",),
        provenance_records=(),
        s3_bytes_read=1024,
    ).to_dict()
    assert "2026-06-01" not in trust["generated_sql"]
    assert trust["bindings"]["start"] == "2026-06-01"
    assert trust["source_manifests"][0]["redacted"] is True


def test_provenance_contract_does_not_claim_unadopted_formula() -> None:
    record = ProvenanceRecord(
        record_id="cudos-amortized-cost-research",
        upstream_repository="aws-solutions-library-samples/example",
        upstream_commit="a" * 40,
        licence="MIT-0",
        source_file="definition.yaml",
        source_locator="calculated field: amortized cost",
        upstream_blob_hash="b" * 40,
        adaptation_type="research-only",
        verification_status="verified",
    )
    assert record.to_dict()["kulshan_formula_id"] is None
    adopted = record.to_dict()
    adopted["adaptation_type"] = "adapted-formula"
    with pytest.raises(ReckonerContractError, match="destination"):
        ProvenanceRecord.from_dict(adopted)


def test_safe_json_compatible_yaml_module_loading() -> None:
    module = load_module(FIXTURES / "sample-module.yaml")
    assert isinstance(module, ModuleDefinition)
    assert module.schema_version == MODULE_SCHEMA_VERSION
    assert module.query_defaults.metric == "unblended-cost"
    assert module.formula_provenance_references == ()


@pytest.mark.parametrize("forbidden", ["sql", "python", "shell", "credentials", "expression"])
def test_module_rejects_executable_or_sensitive_fields(tmp_path: Path, forbidden: str) -> None:
    payload = json.loads((FIXTURES / "sample-module.yaml").read_text(encoding="utf-8"))
    payload[forbidden] = "do something"
    path = tmp_path / "bad.yaml"
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ReckonerContractError):
        load_module(path)


def test_module_rejects_unknown_or_future_schema_and_unsafe_yaml(tmp_path: Path) -> None:
    payload = json.loads((FIXTURES / "sample-module.yaml").read_text(encoding="utf-8"))
    payload["schema_version"] = "2.0"
    path = tmp_path / "future.yaml"
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ReckonerContractError, match="schema_version"):
        load_module(path)
    path.write_text("!!python/object/apply:os.system ['whoami']", encoding="utf-8")
    with pytest.raises(ReckonerContractError, match="JSON-compatible"):
        load_module(path)
