from pathlib import Path

import duckdb
import pytest

from kulshan.reckoner.contracts import (
    ExecutionSource,
    FilterOperator,
    FilterSpec,
    PeriodSpec,
    QuerySpec,
    SortDirection,
    SortSpec,
)
from kulshan.reckoner.cost import ParquetSource, build_canonical_relation
from kulshan.reckoner.explore import (
    built_in_modules,
    choices,
    drilldown,
    export_breadcrumb,
    module_by_id,
    start,
)
from kulshan.reckoner.query import QueryExecutionError, execute_query, inspect_query, plan_source
from kulshan.reckoner.renderers import provenance_sidecar, render_csv, render_json, render_markdown
from kulshan.reckoner.saved import load_saved_query, save_query


def _write_cur(path: Path) -> None:
    connection = duckdb.connect()
    try:
        connection.execute(
            "CREATE TABLE source AS SELECT * FROM (VALUES (TIMESTAMP '2026-01-02', 'Usage', 'CAD', 4.0, 'Amazon EC2')) AS v(line_item_usage_start_date, line_item_line_item_type, line_item_currency_code, line_item_unblended_cost, product_product_name)"  # noqa: E501
        )
        connection.execute("COPY source TO ? (FORMAT PARQUET)", [str(path)])
    finally:
        connection.close()


def test_source_planner_is_explicit_and_explains_unavailable_sources() -> None:
    query = QuerySpec(
        metric="unblended-cost",
        period=PeriodSpec("custom", "2026-01-01", "2026-02-01"),
        execution_source=ExecutionSource.LOCAL,
    )
    assert plan_source(query, local_available=True).selected_source is ExecutionSource.LOCAL
    assert plan_source(query, local_available=False).selected_source is None
    s3 = QuerySpec(
        metric="unblended-cost",
        period=PeriodSpec("custom", "2026-01-01", "2026-02-01"),
        execution_source=ExecutionSource.S3,
    )
    assert plan_source(s3, local_available=True).confirmation_required is True


def test_local_query_returns_renderer_neutral_result_and_trust_inspection(tmp_path: Path) -> None:
    parquet = tmp_path / "cost.parquet"
    _write_cur(parquet)
    connection = duckdb.connect()
    try:
        relation = build_canonical_relation(connection, ParquetSource((str(parquet),)))
        query = QuerySpec(
            metric="unblended-cost",
            period=PeriodSpec("custom", "2026-01-01", "2026-02-01"),
            groupings=("service",),
            execution_source=ExecutionSource.LOCAL,
        )
        result = execute_query(connection, relation, query)
        assert result.formula_id == "kulshan.unblended-cost"
        assert result.rows_returned == len(result.rows)
        inspection = inspect_query(query, result)
        assert inspection.generated_sql == result.generated_sql
        assert inspection.bindings["period_start"] == "2026-01-01"
    finally:
        connection.close()


def test_named_periods_are_not_silently_guessed() -> None:
    query = QuerySpec(metric="unblended-cost", period=PeriodSpec("last-30-days"))
    with pytest.raises(QueryExecutionError, match="period resolution"):
        execute_query(None, None, query)


def test_query_filters_exclusions_sort_and_limit_are_parameterized(tmp_path: Path) -> None:
    parquet = tmp_path / "cost.parquet"
    _write_cur(parquet)
    connection = duckdb.connect()
    try:
        relation = build_canonical_relation(connection, ParquetSource((str(parquet),)))
        query = QuerySpec(
            metric="unblended-cost",
            period=PeriodSpec("custom", "2026-01-01", "2026-02-01"),
            groupings=("service",),
            filters=(FilterSpec("service", FilterOperator.EQUALS, ("Amazon EC2",)),),
            exclusions=(),
            sort=(SortSpec("value", SortDirection.DESCENDING),),
            limit=1,
            execution_source=ExecutionSource.LOCAL,
        )
        result = execute_query(connection, relation, query)
        assert result.rows_returned == 1
        assert result.rows[0]["service_name"] == "Amazon EC2"
        assert "?" in (result.generated_sql or "")
    finally:
        connection.close()


def test_guided_modules_are_stable_and_breadcrumbs_immutable() -> None:
    modules = built_in_modules()
    assert [item.module_id for item in modules] == [
        "where-spending",
        "what-changed",
        "movers",
        "new-charges",
    ]
    assert [item.module_id for item in choices(modules)] == sorted(
        item.module_id for item in modules
    )
    breadcrumb = start(modules[0])
    next_breadcrumb = drilldown(breadcrumb, "account")
    assert breadcrumb.path == ()
    assert next_breadcrumb.path == ("account",)
    with pytest.raises(ValueError):
        drilldown(next_breadcrumb, "account")
    assert module_by_id("movers").module_id == "movers"
    assert export_breadcrumb(next_breadcrumb)["path"] == ["account"]


def test_saved_query_round_trip_is_strict_json(tmp_path: Path) -> None:
    query = QuerySpec(metric="unblended-cost", period=PeriodSpec("last-7-days"))
    path = tmp_path / "query.json"
    save_query(query, path)
    assert load_saved_query(path).to_dict() == query.to_dict()


def test_shared_renderers_preserve_query_result_contract(tmp_path: Path) -> None:
    parquet = tmp_path / "cost.parquet"
    _write_cur(parquet)
    connection = duckdb.connect()
    try:
        relation = build_canonical_relation(connection, ParquetSource((str(parquet),)))
        result = execute_query(
            connection,
            relation,
            QuerySpec(
                metric="unblended-cost",
                period=PeriodSpec("custom", "2026-01-01", "2026-02-01"),
                execution_source=ExecutionSource.LOCAL,
            ),
        )
        assert '"formula_id"' in render_json(result)
        assert "value" in render_csv(result)
        assert "| value |" in render_markdown(result)
        assert provenance_sidecar(result)["formula_id"] == result.formula_id
    finally:
        connection.close()
