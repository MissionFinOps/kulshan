"""Full-schema pseudonymized CUR export via DuckDB.

Supports BOTH local Parquet and S3/Data Export sources.
Uses set-based pseudonymization (distinct values -> temp mapping table -> join)
rather than per-row UDF for performance on large datasets.
Parquet output with zstd compression. Row-level, never aggregated.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from kulshan.cur.duckdb_engine import connect_memory, cur_raw_columns, register_cur_raw
from kulshan.cur.errors import CurDataError
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
    s3_session: Any = None,
    s3_manifest: Any = None,
) -> CurExportResult:
    """Export scoped, pseudonymized CUR data to Parquet.

    Uses DuckDB for all heavy lifting. Set-based pseudonymization:
    distinct identifiers are collected, pseudonymized in Python, then joined
    back via ephemeral temp tables. No per-row Python UDF on the hot path.

    Args:
        cur_path: Path to local CUR Parquet source (ignored if s3_manifest provided).
        scope: EvidenceScope defining date/account/service filters.
        engine: Active PseudonymizationEngine (consultant-strict policy).
        output_dir: Directory to write output Parquet file(s).
        keep_tags: Tag keys explicitly opted-in via --keep-tag.
        drop_unclassified: If True, drop unclassified columns instead of blocking.
        s3_session: boto3 session for S3 source (optional).
        s3_manifest: ManifestIndex for S3/Data Export source (optional).

    Returns:
        CurExportResult with metadata.

    Raises:
        ExportBlockedError: If unclassified columns exist and drop_unclassified=False.
    """
    # Connect to appropriate source
    if s3_manifest is not None:
        from kulshan.cur.s3_query import connect_s3_duckdb
        con = connect_s3_duckdb(session=s3_session)
        # Register the S3 source as cur_raw view
        from kulshan.cur.s3_query import _source_sql
        con.execute(f"CREATE VIEW cur_raw AS SELECT * FROM {_source_sql(s3_manifest)}")
        columns = {str(row[0]).lower() for row in con.execute("DESCRIBE cur_raw").fetchall()}
        from kulshan.cur.schema import resolve_cur_columns
        mapping = resolve_cur_columns(columns)
    else:
        source = local_parquet_source(cur_path)
        con = connect_memory()
        mapping = register_cur_raw(con, source)
        columns = cur_raw_columns(con)

    try:
        # Classify all columns
        classification = classify_all_columns(columns, keep_tags)

        # Check for unclassified
        unclassified = [c for c, cls in classification.items() if cls == ColumnClass.UNCLASSIFIED]
        if unclassified and not drop_unclassified:
            raise ExportBlockedError(
                f"Export blocked: {len(unclassified)} unclassified column(s): "
                f"{', '.join(sorted(unclassified))}"
            )

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

        # Size estimation and warning
        if source_count > 20_000_000:
            import sys
            print(
                f"WARNING: Scoped CUR contains {source_count:,} rows. "
                "This is a large export.",
                file=sys.stderr,
            )

        # ── Set-based pseudonymization ───────────────────────────────────
        # For each PSEUDONYMIZE column: collect distinct values, derive aliases,
        # create ephemeral mapping table, then join into final projection.
        pseudo_cols = [
            c for c, cls in classification.items()
            if cls == ColumnClass.PSEUDONYMIZE and c in columns
        ]
        _create_mapping_tables(con, pseudo_cols, where, engine)

        # Build SELECT with per-column transforms
        select_exprs = []
        dropped = []
        for col in sorted(columns):
            cls = classification[col]
            if cls == ColumnClass.SAFE:
                select_exprs.append(f'cur_raw."{col}"')
            elif cls == ColumnClass.PSEUDONYMIZE:
                # Use the pre-computed mapping table
                map_alias = f"_map_{col}"
                select_exprs.append(f'{map_alias}.alias AS "{col}"')
            elif cls == ColumnClass.DROP:
                dropped.append(col)
            elif cls == ColumnClass.UNCLASSIFIED:
                if drop_unclassified:
                    dropped.append(col)

        # Build JOIN clauses for mapping tables
        join_clauses = []
        for col in sorted(pseudo_cols):
            map_table = f"_pseudo_map_{col}"
            map_alias = f"_map_{col}"
            join_clauses.append(
                f'LEFT JOIN {map_table} AS {map_alias} '
                f'ON CAST(cur_raw."{col}" AS VARCHAR) = {map_alias}.raw_value'
            )

        # Execute export
        output_path = output_dir / "billing.parquet"
        output_dir.mkdir(parents=True, exist_ok=True)

        select_clause = ", ".join(select_exprs)
        joins = " ".join(join_clauses)
        export_sql = (
            f"COPY (SELECT {select_clause} FROM cur_raw {joins} WHERE {where}) "
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


def _create_mapping_tables(
    con: Any,
    pseudo_cols: list[str],
    where: str,
    engine: PseudonymizationEngine,
) -> None:
    """Create ephemeral temp mapping tables for set-based pseudonymization.

    For each column:
    1. SELECT DISTINCT raw values
    2. Derive alias via the existing HMAC engine
    3. CREATE TEMP TABLE with (raw_value, alias)
    """
    for col in pseudo_cols:
        id_class = _infer_identifier_class(col)
        # Get distinct values
        rows = con.execute(
            f'SELECT DISTINCT CAST("{col}" AS VARCHAR) AS v '
            f"FROM cur_raw WHERE {where} AND \"{col}\" IS NOT NULL"
        ).fetchall()

        # Derive aliases
        mappings = []
        for (raw_val,) in rows:
            if raw_val and raw_val.strip():
                alias = engine.pseudonymize_value(raw_val, id_class)
                mappings.append((raw_val, alias))
            else:
                mappings.append((raw_val, raw_val))

        # Create temp table
        table_name = f"_pseudo_map_{col}"
        con.execute(f"CREATE TEMP TABLE {table_name} (raw_value VARCHAR, alias VARCHAR)")
        if mappings:
            con.executemany(
                f"INSERT INTO {table_name} VALUES (?, ?)", mappings
            )


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
