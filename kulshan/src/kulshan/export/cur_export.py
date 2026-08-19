"""Full-schema pseudonymized CUR export via DuckDB.

Uses DuckDB COPY with per-column transformation. No pandas round-trip.
Parquet output with zstd compression. Row-level, never aggregated.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from kulshan.cur.duckdb_engine import connect_memory, cur_raw_columns, register_cur_raw
from kulshan.cur.source import local_parquet_source
from kulshan.export.columns import ColumnClass, classify_all_columns
from kulshan.export.scope import EvidenceScope
from kulshan.pseudonym.engine import PseudonymizationEngine
from kulshan.pseudonym.types import IdentifierClass


@dataclass
class CurExportResult:
    """Result of a CUR export operation."""
    output_path: Path
    row_count: int
    column_count: int
    classification: dict[str, ColumnClass]
    source_row_count: int
    dropped_columns: list[str]


def export_cur(
    cur_path: str,
    scope: EvidenceScope,
    engine: PseudonymizationEngine,
    output_dir: Path,
    keep_tags: frozenset[str] = frozenset(),
    drop_unclassified: bool = False,
) -> CurExportResult:
    """Export scoped, pseudonymized CUR data to Parquet.

    Uses DuckDB for all heavy lifting. Python UDFs handle pseudonymization.
    No full dataset materialization in Python memory.

    Args:
        cur_path: Path to local CUR Parquet source.
        scope: EvidenceScope defining date/account/service filters.
        engine: Active PseudonymizationEngine (consultant-strict policy).
        output_dir: Directory to write output Parquet file(s).
        keep_tags: Tag keys explicitly opted-in via --keep-tag.
        drop_unclassified: If True, drop unclassified columns instead of blocking.

    Returns:
        CurExportResult with metadata.

    Raises:
        ExportBlockedError: If unclassified columns exist and drop_unclassified=False.
    """
    source = local_parquet_source(cur_path)
    con = connect_memory()
    try:
        mapping = register_cur_raw(con, source)
        columns = cur_raw_columns(con)

        # Classify all columns
        classification = classify_all_columns(columns, keep_tags)

        # Check for unclassified
        unclassified = [c for c, cls in classification.items() if cls == ColumnClass.UNCLASSIFIED]
        if unclassified and not drop_unclassified:
            raise ExportBlockedError(
                f"Export blocked: {len(unclassified)} unclassified column(s): "
                f"{', '.join(sorted(unclassified))}"
            )

        # Register pseudonymization UDFs
        _register_udfs(con, engine)

        # Build SELECT with per-column transforms
        select_exprs = []
        dropped = []
        for col in sorted(columns):
            cls = classification[col]
            if cls == ColumnClass.SAFE:
                select_exprs.append(f'"{col}"')
            elif cls == ColumnClass.PSEUDONYMIZE:
                id_class = _infer_identifier_class(col)
                select_exprs.append(
                    f'kulshan_pseudo("{col}", CAST("{col}" AS VARCHAR), \'{id_class.value}\') AS "{col}"'
                )
            elif cls == ColumnClass.DROP:
                dropped.append(col)
            elif cls == ColumnClass.UNCLASSIFIED:
                if drop_unclassified:
                    dropped.append(col)
                # else: already raised above

        # Build WHERE clause from scope
        where = scope.duckdb_where_clause(
            date_col=mapping.usage_start,
            account_col=mapping.account_id,
            service_col=mapping.service,
        )

        # Count source rows matching scope
        source_count = int(
            con.execute(f"SELECT COUNT(*) FROM cur_raw WHERE {where}").fetchone()[0]
        )

        # Execute export
        output_path = output_dir / "billing.parquet"
        output_dir.mkdir(parents=True, exist_ok=True)

        select_clause = ", ".join(select_exprs)
        export_sql = (
            f"COPY (SELECT {select_clause} FROM cur_raw WHERE {where}) "
            f"TO '{output_path.as_posix()}' (FORMAT PARQUET, CODEC 'ZSTD')"
        )
        con.execute(export_sql)

        # Verify output row count
        output_count = int(
            con.execute(
                f"SELECT COUNT(*) FROM read_parquet('{output_path.as_posix()}')"
            ).fetchone()[0]
        )

        return CurExportResult(
            output_path=output_path,
            row_count=output_count,
            column_count=len(select_exprs),
            classification=classification,
            source_row_count=source_count,
            dropped_columns=dropped,
        )
    finally:
        con.close()


def _register_udfs(con: Any, engine: PseudonymizationEngine) -> None:
    """Register pseudonymization as a DuckDB scalar UDF."""
    def pseudo_fn(col_name: str, value: str, id_class_str: str) -> str:
        if not value or value.strip() == "":
            return value
        id_class = IdentifierClass(id_class_str)
        return engine.pseudonymize_value(value, id_class)

    con.create_function("kulshan_pseudo", pseudo_fn, [str, str, str], str)


def _infer_identifier_class(column_name: str) -> IdentifierClass:
    """Map a CUR column name to an identifier class for pseudonymization."""
    col = column_name.lower()
    if "account" in col:
        return IdentifierClass.ACCOUNT
    if "resource_id" in col or "resourceid" in col:
        return IdentifierClass.RESOURCE
    if "invoice" in col:
        return IdentifierClass.INVOICE
    if "savings_plan" in col and "arn" in col:
        return IdentifierClass.SAVINGS_PLAN
    if "reservation" in col and ("arn" in col or "subscription" in col):
        return IdentifierClass.RESERVED_INSTANCE
    if col.startswith("resource_tags_"):
        return IdentifierClass.TAG_VALUE
    return IdentifierClass.UNKNOWN


class ExportBlockedError(Exception):
    """Export cannot proceed due to unclassified columns or validation failure."""
    pass
