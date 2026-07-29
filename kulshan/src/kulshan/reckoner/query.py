"""Renderer-neutral semantic query execution over the canonical relation."""

from __future__ import annotations

import time
from datetime import timedelta
from typing import Any

from kulshan.reckoner.contracts import (
    ColumnDefinition,
    ExecutionSource,
    PlannerDecision,
    PlannerReason,
    QueryResult,
    QuerySpec,
    ResolvedRange,
    TrustInspection,
)
from kulshan.reckoner.cost.semantics import GROUPINGS, CanonicalRelation, select_formula


class QueryExecutionError(RuntimeError):
    """A QuerySpec cannot be satisfied by the selected source."""


def plan_source(
    query: QuerySpec, *, local_available: bool, cache_coverage: str | None = None
) -> PlannerDecision:
    if query.execution_source is ExecutionSource.LOCAL:
        if not local_available:
            return PlannerDecision(
                None,
                PlannerReason.UNSATISFIED,
                local_data_available=False,
                unsatisfied_requirement="local data is unavailable",
            )
        return PlannerDecision(
            ExecutionSource.LOCAL, PlannerReason.EXPLICIT_REQUEST, local_data_available=True
        )
    if query.execution_source is ExecutionSource.CACHE:
        if not cache_coverage:
            return PlannerDecision(
                None,
                PlannerReason.UNSATISFIED,
                cache_coverage=None,
                unsatisfied_requirement="cache coverage is unavailable",
            )
        return PlannerDecision(
            ExecutionSource.CACHE, PlannerReason.EXPLICIT_REQUEST, cache_coverage=cache_coverage
        )
    if query.execution_source is ExecutionSource.S3:
        return PlannerDecision(
            ExecutionSource.S3,
            PlannerReason.EXPLICIT_REQUEST,
            s3_estimate_required=True,
            confirmation_required=True,
        )
    if cache_coverage:
        return PlannerDecision(
            ExecutionSource.CACHE, PlannerReason.CACHE_COVERAGE, cache_coverage=cache_coverage
        )
    if local_available:
        return PlannerDecision(
            ExecutionSource.LOCAL, PlannerReason.LOCAL_AVAILABLE, local_data_available=True
        )
    return PlannerDecision(
        None, PlannerReason.UNSATISFIED, unsatisfied_requirement="no eligible execution source"
    )


def _resolved_period(
    connection: Any, relation: CanonicalRelation, query: QuerySpec
) -> ResolvedRange:
    if query.period.period_id == "custom":
        return ResolvedRange(query.period.start or "", query.period.end or "")
    if connection is None or relation is None:
        raise QueryExecutionError("period resolution requires a relation")
    row = connection.execute(
        f"SELECT MIN(usage_start), MAX(usage_start) FROM {relation.relation_name}"
    ).fetchone()
    if not row or row[0] is None:
        raise QueryExecutionError("cannot resolve named period from an empty relation")
    end = row[1] + timedelta(days=1)
    days = {"last-7-days": 7, "last-30-days": 30}.get(query.period.period_id)
    if days:
        start = end - timedelta(days=days)
    elif query.period.period_id == "current-billing-period":
        start = row[0].replace(day=1)
    else:
        raise QueryExecutionError(
            f"named period {query.period.period_id} requires period discovery"
        )
    return ResolvedRange(start.isoformat(), end.isoformat())


def execute_query(connection: Any, relation: CanonicalRelation, query: QuerySpec) -> QueryResult:
    if query.execution_source not in {ExecutionSource.AUTO, ExecutionSource.LOCAL}:
        raise QueryExecutionError("this PR 5 executor accepts only local canonical relations")
    source_plan = plan_source(query, local_available=True)
    if source_plan.selected_source is None:
        raise QueryExecutionError(source_plan.unsatisfied_requirement or "no source")
    period = _resolved_period(connection, relation, query)
    formula, _auto = select_formula(relation, query.metric)
    unknown = [item for item in query.groupings if item not in GROUPINGS]
    if unknown or len(query.groupings) > 3:
        raise QueryExecutionError(f"unsupported grouping: {unknown}")
    groups = [GROUPINGS[item] for item in query.groupings]
    group_sql = ", ".join('"' + item + '"' for item in groups)
    prefix = f"{group_sql}, " if group_sql else ""
    group_by = f" GROUP BY {group_sql}" if group_sql else ""
    start = time.perf_counter()
    sql = (
        f'SELECT {prefix}SUM({formula.expression}) AS value FROM "{relation.relation_name}" '
        f"WHERE usage_start >= CAST(? AS TIMESTAMP) "
        f"AND usage_start < CAST(? AS TIMESTAMP){group_by}"
    )
    cursor = connection.execute(sql, [period.start, period.end])
    names = [column[0] for column in cursor.description]
    rows = tuple(dict(zip(names, row)) for row in cursor.fetchall())
    duration = int((time.perf_counter() - start) * 1000)
    columns = tuple(
        ColumnDefinition(item, item.replace("_", " ").title(), "string") for item in groups
    ) + (ColumnDefinition("value", formula.metric_id, "number", unit="currency"),)
    return QueryResult(
        query=query,
        period=period,
        execution_source=ExecutionSource.LOCAL,
        columns=columns,
        rows=rows,
        totals={"value": sum(float(row["value"] or 0) for row in rows)},
        cost_basis={"metric": formula.metric_id},
        formula_id=formula.formula_id,
        formula_version=formula.formula_version,
        provisional=True,
        limitations=formula.limitations,
        generated_sql=sql,
        bindings={"period_start": period.start, "period_end": period.end},
        rows_scanned=None,
        rows_returned=len(rows),
        execution_duration_ms=duration,
    )


def inspect_query(query: QuerySpec, result: QueryResult) -> TrustInspection:
    return TrustInspection(
        metric=query.metric,
        cost_basis=result.cost_basis,
        formula_id=result.formula_id,
        formula_version=result.formula_version,
        period=result.period,
        comparison_period=result.comparison_period,
        groupings=query.groupings,
        filters=query.filters,
        exclusions=query.exclusions,
        execution_source=result.execution_source,
        cache_coverage=None,
        freshness=result.freshness,
        limitations=result.limitations,
        generated_sql=result.generated_sql,
        bindings=result.bindings,
        source_manifests=result.source_manifests,
        schema_fingerprints=(),
        provenance_records=(),
        s3_bytes_read=result.s3_bytes_read,
    )
