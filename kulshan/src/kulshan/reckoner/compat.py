"""Compatibility bridge for existing analyze commands."""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any

from kulshan.reckoner.contracts import ExecutionSource, PeriodSpec, QuerySpec
from kulshan.reckoner.cost.semantics import ParquetSource, open_local_relation
from kulshan.reckoner.query import execute_query


def reckoner_cost_totals(
    cur_path: str | Path,
    month: str,
    *,
    groupings: tuple[str, ...] = ("service",),
) -> dict[str, Any]:
    """Execute a canonical monthly cost query for compatibility validation."""
    try:
        year, month_number = (int(item) for item in month.split("-", 1))
        period_start = date(year, month_number, 1)
    except (TypeError, ValueError) as exc:
        raise ValueError("month must use YYYY-MM format") from exc

    period_end = date(year + 1, 1, 1) if month_number == 12 else date(year, month_number + 1, 1)

    path = Path(cur_path)
    files = (
        (path,) if path.is_file() and path.suffix.lower() == ".parquet" else path.rglob("*.parquet")
    )
    locations = tuple(str(item.resolve()) for item in sorted(files))
    if not locations:
        return {"available": False, "reason": "no parquet files found"}

    source = ParquetSource(locations)
    with open_local_relation(source) as (connection, relation):
        query = QuerySpec(
            metric="unblended-cost",
            period=PeriodSpec(
                "custom",
                start=period_start.isoformat(),
                end=period_end.isoformat(),
            ),
            groupings=groupings,
            execution_source=ExecutionSource.LOCAL,
        )
        return execute_query(connection, relation, query).to_dict()
