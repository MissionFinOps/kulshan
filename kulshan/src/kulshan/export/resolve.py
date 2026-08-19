"""Forward alias resolution: given an alias, find the matching real identifier.

Since 0.5.1 uses stateless HMAC (no mapping store), resolution works by:
1. Enumerating candidate identifiers from the workspace's local CUR data
2. Deriving each candidate's alias using the same HMAC engine
3. Returning the match

This is a forward lookup, not reversal.
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

import click
from rich.console import Console

from kulshan.pseudonym.context import resolve_workspace_secret_path
from kulshan.pseudonym.engine import PseudonymizationEngine
from kulshan.pseudonym.policy import PseudonymPolicy
from kulshan.pseudonym.types import IdentifierClass


def resolve_alias(
    alias: str,
    cur_path: Optional[str] = None,
) -> Optional[str]:
    """Resolve an alias back to its real identifier by forward lookup.

    Args:
        alias: The pseudonym alias (e.g., acct_7f31c2a9102d774b).
        cur_path: Path to CUR data for enumerating candidates.

    Returns:
        The real identifier, or None if not found.
    """
    ws_path = resolve_workspace_secret_path()
    policy = PseudonymPolicy(mode="normal", tty_bypass=False, show_identifiers=False)
    engine = PseudonymizationEngine.create(ws_path, policy)

    # Determine identifier class from prefix
    prefix = alias.split("_")[0] if "_" in alias else ""
    id_class = _prefix_to_class(prefix)
    if id_class is None:
        return None

    # Enumerate candidates from CUR if available
    candidates = set()
    if cur_path:
        candidates = _enumerate_candidates(cur_path, id_class)

    # Try each candidate
    for candidate in candidates:
        derived = engine.pseudonymize_value(candidate, id_class)
        if derived == alias:
            return candidate

    return None


def _prefix_to_class(prefix: str) -> Optional[IdentifierClass]:
    """Map alias prefix back to IdentifierClass."""
    mapping = {
        "acct": IdentifierClass.ACCOUNT,
        "res": IdentifierClass.RESOURCE,
        "arn": IdentifierClass.ARN,
        "sp": IdentifierClass.SAVINGS_PLAN,
        "ri": IdentifierClass.RESERVED_INSTANCE,
        "inv": IdentifierClass.INVOICE,
        "bucket": IdentifierClass.S3_BUCKET,
        "host": IdentifierClass.HOSTNAME,
        "user": IdentifierClass.EMAIL,
        "ip": IdentifierClass.IP_ADDRESS,
        "tag": IdentifierClass.TAG_VALUE,
        "id": IdentifierClass.UNKNOWN,
    }
    return mapping.get(prefix)


def _enumerate_candidates(cur_path: str, id_class: IdentifierClass) -> set[str]:
    """Enumerate distinct identifier values from CUR for the given class."""
    from kulshan.cur.duckdb_engine import connect_memory, cur_raw_columns, register_cur_raw
    from kulshan.cur.source import local_parquet_source

    source = local_parquet_source(cur_path)
    con = connect_memory()
    try:
        mapping = register_cur_raw(con, source)
        columns = cur_raw_columns(con)

        # Map identifier class to likely CUR columns
        target_cols = _class_to_cur_columns(id_class, columns, mapping)
        candidates: set[str] = set()

        for col in target_cols:
            try:
                rows = con.execute(
                    f'SELECT DISTINCT CAST("{col}" AS VARCHAR) FROM cur_raw '
                    f'WHERE "{col}" IS NOT NULL LIMIT 50000'
                ).fetchall()
                for row in rows:
                    val = str(row[0]).strip()
                    if val:
                        candidates.add(val)
            except Exception:
                continue

        return candidates
    finally:
        con.close()


def _class_to_cur_columns(
    id_class: IdentifierClass,
    columns: set[str],
    mapping,
) -> list[str]:
    """Map identifier class to CUR column names for candidate enumeration."""
    if id_class == IdentifierClass.ACCOUNT:
        candidates = ["line_item_usage_account_id", "bill_payer_account_id",
                      "lineitem_usageaccountid", "bill_payeraccountid"]
        return [c for c in candidates if c in columns]
    if id_class == IdentifierClass.RESOURCE:
        candidates = ["line_item_resource_id", "lineitem_resourceid"]
        return [c for c in candidates if c in columns]
    if id_class == IdentifierClass.TAG_VALUE:
        return [c for c in columns if c.startswith("resource_tags_")]
    if id_class == IdentifierClass.SAVINGS_PLAN:
        candidates = ["savings_plan_savings_plan_a_r_n"]
        return [c for c in candidates if c in columns]
    if id_class == IdentifierClass.RESERVED_INSTANCE:
        candidates = ["reservation_reservation_a_r_n"]
        return [c for c in candidates if c in columns]
    return []
