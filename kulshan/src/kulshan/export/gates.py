"""Fail-closed validation gates for consultant evidence export.

All three gates must pass before a ZIP is created.
Any failure deletes intermediate artifacts and exits non-zero.
"""
from __future__ import annotations

import ipaddress
import re
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from kulshan.export.columns import ColumnClass

# ---------------------------------------------------------------------------
# Gate results
# ---------------------------------------------------------------------------

@dataclass
class GateResult:
    passed: bool
    gate: str
    details: dict[str, Any] = field(default_factory=dict)
    failures: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Gate 1: Schema classification
# ---------------------------------------------------------------------------

def gate_schema(
    classification: dict[str, ColumnClass],
    drop_unclassified: bool = False,
) -> GateResult:
    """Every output column must be classified. No unclassified column survives.

    Args:
        classification: Dict of column_name -> ColumnClass.
        drop_unclassified: If True, unclassified columns are dropped (not blocked).

    Returns:
        GateResult with pass/fail and classification counts.
    """
    counts = {c: 0 for c in ColumnClass}
    unclassified = []
    for col, cls in classification.items():
        counts[cls] += 1
        if cls == ColumnClass.UNCLASSIFIED:
            unclassified.append(col)

    if unclassified and not drop_unclassified:
        return GateResult(
            passed=False,
            gate="schema",
            details={"counts": {k.value: v for k, v in counts.items()}, "total": len(classification)},
            failures=[f"Unclassified column: {col}" for col in sorted(unclassified)],
        )

    return GateResult(
        passed=True,
        gate="schema",
        details={
            "counts": {k.value: v for k, v in counts.items()},
            "total": len(classification),
            "dropped_unclassified": sorted(unclassified) if drop_unclassified else [],
        },
    )


# ---------------------------------------------------------------------------
# Gate 2: Evidence integrity (multiset row equivalence)
# ---------------------------------------------------------------------------

def gate_integrity(
    source_row_count: int,
    output_row_count: int,
    source_path: str | None = None,
    output_path: str | None = None,
    numeric_columns: list[str] | None = None,
    pseudo_columns: list[str] | None = None,
    safe_dimensions: list[str] | None = None,
    engine: Any = None,
    scope: Any | None = None,
    s3_manifest: Any = None,
    s3_session: Any = None,
) -> GateResult:
    """Multiset row equivalence between independently-built source and output projections.

    The SOURCE side applies the same EvidenceScope as the export, independently
    re-derives pseudonym mappings, then builds a validation projection.

    Compares validation projections via:
        SOURCE_VALIDATION EXCEPT ALL OUTPUT_VALIDATION = 0 rows
        OUTPUT_VALIDATION EXCEPT ALL SOURCE_VALIDATION = 0 rows

    This handles legitimate duplicate rows correctly (multiplicity matters).
    No globally unique row identifier is required.

    Numeric cost/usage fields are compared in their native DuckDB types
    (DOUBLE, DECIMAL, BIGINT, INTEGER) without casting to VARCHAR.

    Args:
        source_row_count: Expected row count from scoped source.
        output_row_count: Actual row count in exported Parquet.
        source_path: DuckDB-readable source Parquet (original raw data).
        output_path: Exported Parquet file path.
        numeric_columns: SAFE numeric cost/usage columns to verify preservation.
        pseudo_columns: PSEUDONYMIZE columns (for building distinguishing dimensions).
        safe_dimensions: Non-numeric SAFE columns useful for distinguishing rows.
        engine: PseudonymizationEngine for independent source-side derivation.
        scope: EvidenceScope to apply to source before comparison (same scope as export).
        s3_manifest: ManifestIndex for an S3/Data Export source.
        s3_session: boto3 session used to read the S3 source.
    """
    failures = []

    if source_row_count != output_row_count:
        failures.append(
            f"Row count mismatch: source={source_row_count}, output={output_row_count}"
        )

    # Multiset comparison via EXCEPT ALL
    has_source = bool(source_path) or s3_manifest is not None
    validation_columns = bool(numeric_columns or pseudo_columns or safe_dimensions)
    if has_source and output_path and validation_columns and engine is not None:
        from kulshan.export.cur_export import _infer_identifier_class

        if s3_manifest is not None:
            from kulshan.cur.s3_query import _source_sql, connect_s3_duckdb

            con = connect_s3_duckdb(session=s3_session)
            raw_source_sql = _source_sql(s3_manifest)
        else:
            import duckdb

            con = duckdb.connect(":memory:")
            escaped_source = str(source_path).replace("'", "''")
            raw_source_sql = f"read_parquet('{escaped_source}')"
        try:
            # Read raw source and apply scope filter independently
            con.execute(
                f"CREATE VIEW gate2_raw_source AS SELECT * FROM {raw_source_sql}"
            )
            src_cols = {
                str(r[0]).lower()
                for r in con.execute("DESCRIBE gate2_raw_source").fetchall()
            }

            # Build scope WHERE clause if scope provided
            scope_where = "TRUE"
            if scope is not None:
                from kulshan.cur.schema import resolve_cur_columns
                mapping = resolve_cur_columns(src_cols)
                scope_where = scope.duckdb_where_clause(
                    date_col=mapping.usage_start,
                    account_col=mapping.account_id,
                    service_col=mapping.service,
                )

            # Create scoped source view
            con.execute(
                f"CREATE VIEW gate2_source AS SELECT * FROM gate2_raw_source WHERE {scope_where}"
            )

            # Create fresh pseudonymization mappings from SCOPED source (independent derivation)
            pseudo_in_source = [c for c in (pseudo_columns or []) if c in src_cols]
            if pseudo_in_source:
                for col in pseudo_in_source:
                    id_class = _infer_identifier_class(col)
                    rows = con.execute(
                        f'SELECT DISTINCT CAST("{col}" AS VARCHAR) AS v '
                        f'FROM gate2_source WHERE "{col}" IS NOT NULL'
                    ).fetchall()
                    mappings = []
                    for (raw_val,) in rows:
                        if raw_val and raw_val.strip():
                            alias = engine.pseudonymize_value(raw_val, id_class)
                            mappings.append((raw_val, alias))
                        else:
                            mappings.append((raw_val, raw_val))
                    table_name = f"_pseudo_map_{col}"
                    con.execute(
                        f"CREATE TEMP TABLE {table_name}"
                        " (raw_value VARCHAR, alias VARCHAR)"
                    )
                    if mappings:
                        con.executemany(f"INSERT INTO {table_name} VALUES (?, ?)", mappings)

            # Discover output column types for native numeric comparison
            con.execute(
                f"CREATE VIEW gate2_output AS SELECT * FROM read_parquet('{output_path}')"
            )

            # Build validation column list - use native types for numerics
            val_cols_src = []
            val_cols_out = []

            for col in (numeric_columns or []):
                if col in src_cols:
                    # Use native type directly - no VARCHAR cast
                    val_cols_src.append(f'gate2_source."{col}"')
                    val_cols_out.append(f'gate2_output."{col}"')

            # Add pseudonymized dimensions for row distinction
            for col in pseudo_in_source:
                map_alias = f"_map_{col}"
                val_cols_src.append(f'{map_alias}.alias AS "p_{col}"')
                val_cols_out.append(f'CAST(gate2_output."{col}" AS VARCHAR) AS "p_{col}"')

            # Add safe dimensions for row distinction
            for col in (safe_dimensions or []):
                if col in src_cols:
                    val_cols_src.append(f'CAST(gate2_source."{col}" AS VARCHAR) AS "{col}"')
                    val_cols_out.append(f'CAST(gate2_output."{col}" AS VARCHAR) AS "{col}"')

            if not val_cols_src:
                # No columns to compare beyond row count
                pass
            else:
                # Build source projection with joins
                joins = ""
                for col in pseudo_in_source:
                    map_table = f"_pseudo_map_{col}"
                    map_alias = f"_map_{col}"
                    joins += (
                        f' LEFT JOIN {map_table} AS {map_alias}'
                        f' ON CAST(gate2_source."{col}" AS VARCHAR) = {map_alias}.raw_value'
                    )

                src_select = ", ".join(val_cols_src)
                src_sql = f"SELECT {src_select} FROM gate2_source{joins}"

                out_select = ", ".join(val_cols_out)
                out_sql = f"SELECT {out_select} FROM gate2_output"

                # EXCEPT ALL both directions
                source_minus_output = con.execute(
                    f"SELECT COUNT(*) FROM (({src_sql}) EXCEPT ALL ({out_sql}))"
                ).fetchone()[0]

                output_minus_source = con.execute(
                    f"SELECT COUNT(*) FROM (({out_sql}) EXCEPT ALL ({src_sql}))"
                ).fetchone()[0]

                if source_minus_output > 0:
                    failures.append(
                        f"Source rows not in output: {source_minus_output} "
                        f"(numeric evidence may be corrupted)"
                    )
                if output_minus_source > 0:
                    failures.append(
                        f"Output rows not in source: {output_minus_source} "
                        f"(unexpected data introduced)"
                    )

        except Exception as e:
            failures.append(f"Gate 2 verification error: {type(e).__name__}: {e}")
        finally:
            con.close()

    return GateResult(
        passed=len(failures) == 0,
        gate="integrity",
        details={
            "source_rows": source_row_count,
            "output_rows": output_row_count,
            "numeric_columns_verified": len(numeric_columns) if numeric_columns else 0,
            "method": "multiset_except_all",
        },
        failures=failures,
    )


# ---------------------------------------------------------------------------
# Gate 3: Residual identifier scan
# ---------------------------------------------------------------------------

_ACCOUNT_RE = re.compile(r"\b\d{12}\b")
_ARN_RE = re.compile(r"arn:aws[a-z-]*:[a-z0-9-]+:[a-z0-9-]*:\d{12}:[^\s,\"']+")
_EMAIL_RE = re.compile(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}")

# Octet-validated (0-255), matches public and private IPv4 addresses alike.
# There is no bucket-name equivalent of this: bucket names have no
# distinguishing shape, so they are not regex-detectable at all. Bucket
# coverage instead depends entirely on Gate 1 classifying resource-id-style
# columns PSEUDONYMIZE (see export/columns.py) so a real bucket value is
# already in `source_identifiers` and caught by the membership check below.
_IPV4_OCTET = r"(?:25[0-5]|2[0-4][0-9]|1[0-9][0-9]|[1-9]?[0-9])"
_IPV4_RE = re.compile(rf"\b{_IPV4_OCTET}(?:\.{_IPV4_OCTET}){{3}}\b")

# Reserved ranges that legitimately appear in tests, fixtures, and docs
# (RFC 5737 documentation ranges, loopback, link-local). Excluded so normal
# development artifacts don't trip the gate. Real RFC1918 private ranges are
# intentionally NOT excluded: a private IP is still a residual identifier.
_IPV4_EXCLUDED_NETWORKS = (
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("169.254.0.0/16"),
    ipaddress.ip_network("192.0.2.0/24"),
    ipaddress.ip_network("198.51.100.0/24"),
    ipaddress.ip_network("203.0.113.0/24"),
)

# Below this length, a substring match on a source identifier is too noisy
# to use as-is (see _scan_residual_chunk); above it, substring match stands.
_SHORT_IDENTIFIER_THRESHOLD = 4


def gate_residual(
    source_identifiers: set[str],
    output_text: str | Iterable[str | tuple[str, str]],
    secret_path: Path | None = None,
) -> GateResult:
    """Scan output for residual source identifiers and generic patterns.

    Args:
        source_identifiers: Set of real identifier values from PSEUDONYMIZE columns.
        output_text: Concatenated text content of all output files. Each chunk
            may be a plain string (source unknown) or a (source_label, text)
            tuple, so a failure can name where it fired without printing the
            leaked value itself.
        secret_path: Path to workspace pseudonym.key (must not be in ZIP).
    """
    failures = []
    chunks = [output_text] if isinstance(output_text, str) else output_text
    identifiers_checked = len(source_identifiers)
    secret_hex = None
    if secret_path and secret_path.exists():
        secret_hex = secret_path.read_bytes().hex()

    for chunk in chunks:
        source, text = chunk if isinstance(chunk, tuple) else (None, chunk)
        failures.extend(_scan_residual_chunk(source_identifiers, text, secret_hex, source))

    return GateResult(
        passed=len(failures) == 0,
        gate="residual",
        details={"identifiers_checked": identifiers_checked},
        failures=failures,
    )


def _scan_residual_chunk(
    source_identifiers: set[str],
    output_text: str,
    secret_hex: str | None,
    source: str | None = None,
) -> list[str]:
    # "What was found" is the pattern type and count, never the matched
    # value - printing a leaked account ID or email to the console/CI log
    # to explain the failure would defeat the point of the gate. "Where"
    # (the source label, when known) is safe to print and narrows the fix.
    where = f" (in {source})" if source else ""
    failures = []

    # Check source identifiers don't appear in output.
    # Below the length threshold, a substring match is too noisy (a 3-char
    # tag value like "FIN" would match inside "FINANCE" or "confine"), so use
    # a word-boundary match instead of skipping the value outright. At or
    # above the threshold, a plain substring match is precise enough on its
    # own (real identifiers this long rarely collide with unrelated text).
    for identifier in source_identifiers:
        if not identifier:
            continue
        if len(identifier) < _SHORT_IDENTIFIER_THRESHOLD:
            if re.search(rf"\b{re.escape(identifier)}\b", output_text):
                failures.append(f"Source identifier leaked (length {len(identifier)}){where}")
        elif identifier in output_text:
            failures.append(f"Source identifier leaked (length {len(identifier)}){where}")
            # Do not print the value itself

    # Generic pattern scan.
    # Every 12-digit match is treated as a potential account ID. There is no
    # value-based skip list here: this is the last gate before evidence
    # leaves the customer's environment, so a false positive (blocking a
    # clean export) is the correct failure mode, not a false negative
    # (shipping a leak). A column that legitimately produces 12-digit noise
    # is a Gate 1 classification problem, not something Gate 3 should guess
    # around by value.
    account_matches = _ACCOUNT_RE.findall(output_text)
    if account_matches:
        failures.append(
            f"Potential 12-digit account ID pattern found "
            f"({len(account_matches)} occurrences){where}"
        )

    arn_matches = _ARN_RE.findall(output_text)
    if arn_matches:
        failures.append(f"ARN pattern found ({len(arn_matches)} occurrences){where}")

    email_matches = _EMAIL_RE.findall(output_text)
    # Filter pseudo.invalid emails (those are our aliases)
    real_emails = [e for e in email_matches if not e.endswith("pseudo.invalid")]
    if real_emails:
        failures.append(f"Email pattern found ({len(real_emails)} occurrences){where}")

    ipv4_matches = _IPV4_RE.findall(output_text)
    real_ipv4 = [m for m in ipv4_matches if not _is_excluded_ipv4(m)]
    if real_ipv4:
        failures.append(
            f"IPv4 address pattern found ({len(real_ipv4)} occurrences){where}. "
            f"No CUR column is classified to pseudonymize IP addresses, so this "
            f"gate is the only control for them - it fails closed rather than "
            f"silently passing. If this fired on a legitimate value, the fix is "
            f"a Gate 1 classification for the column it came from, not loosening "
            f"this pattern."
        )

    # Assert key material not present
    if secret_hex and secret_hex in output_text:
        failures.append(f"Workspace secret key material found in output{where}")
    return failures


def _is_excluded_ipv4(value: str) -> bool:
    """True if `value` is a reserved/documentation address, not a real leak."""
    try:
        addr = ipaddress.ip_address(value)
    except ValueError:
        return True
    return any(addr in network for network in _IPV4_EXCLUDED_NETWORKS)
