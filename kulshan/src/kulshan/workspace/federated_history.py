"""Federated history read-through for reconciled environments.

When a workspace has superseded workspaces pointing to it, history
reads include scans from those linked environments. This gives the
user a unified view without physically moving or copying data.

Rules:
- Never writes to superseded workspaces.
- Only includes workspaces whose superseded_by points to the target.
- Only includes workspaces bound to the same verified payer.
- Detects superseded_by cycles and fails safely.
- Deduplicates identical scan IDs.
- Tags each inherited scan with its source workspace.
- The original workspace remains the source of truth.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from kulshan.workspace.config import read_workspace_config
from kulshan.workspace.context import WorkspaceContext
from kulshan.workspace.paths import get_workspace_path, get_workspaces_root
from kulshan.workspace.resolution import list_workspaces

logger = logging.getLogger(__name__)

# Maximum depth for cycle detection
_MAX_DEPTH = 10


@dataclass
class FederatedScan:
    """A scan with source provenance metadata."""

    scan: dict[str, Any]
    source_workspace: str
    source_display_name: str
    is_linked: bool  # True if from a superseded workspace, False if direct


@dataclass
class FederatedHistoryResult:
    """Result of a federated history read."""

    scans: list[FederatedScan]
    linked_workspace_count: int
    linked_scan_count: int


def collect_federated_scans(
    ws_ctx: WorkspaceContext,
    limit: int = 20,
    account_id: str | None = None,
) -> FederatedHistoryResult:
    """Collect scans from the target workspace and all linked superseded workspaces.

    Args:
        ws_ctx: The target workspace context.
        limit: Maximum number of scans to return (after merge+sort).
        account_id: Optional account ID filter (applied to all sources).

    Returns:
        FederatedHistoryResult with merged, sorted, deduplicated scans.
    """
    from kulshan.history import HistoryStore

    # 1. Read direct scans
    direct_scans = _read_scans(ws_ctx.history_db_path, limit=0, account_id=account_id)
    federated = [
        FederatedScan(
            scan=s,
            source_workspace=ws_ctx.name,
            source_display_name=ws_ctx.display_name,
            is_linked=False,
        )
        for s in direct_scans
    ]

    # 2. Find superseded workspaces pointing to this one
    linked_workspaces = _find_linked_workspaces(ws_ctx.name, ws_ctx.payer_account_id)
    linked_scan_count = 0

    for linked_ws_name, linked_display_name, linked_path in linked_workspaces:
        linked_db = linked_path / "history.db"
        if not linked_db.exists():
            continue

        linked_scans = _read_scans(linked_db, limit=0, account_id=account_id)
        linked_scan_count += len(linked_scans)

        for s in linked_scans:
            federated.append(FederatedScan(
                scan=s,
                source_workspace=linked_ws_name,
                source_display_name=linked_display_name,
                is_linked=True,
            ))

    # 3. Deduplicate by scan ID
    seen_ids: set[str] = set()
    deduped: list[FederatedScan] = []
    for fs in federated:
        scan_id = fs.scan.get("id", "")
        if scan_id and scan_id in seen_ids:
            continue
        seen_ids.add(scan_id)
        deduped.append(fs)

    # 4. Sort by timestamp descending
    deduped.sort(key=lambda fs: fs.scan.get("timestamp", ""), reverse=True)

    # 5. Apply limit
    if limit > 0:
        deduped = deduped[:limit]

    return FederatedHistoryResult(
        scans=deduped,
        linked_workspace_count=len(linked_workspaces),
        linked_scan_count=linked_scan_count,
    )


def _find_linked_workspaces(
    target_name: str,
    target_payer: str | None,
) -> list[tuple[str, str, Path]]:
    """Find all workspaces whose superseded_by points to the target.

    Only includes workspaces bound to the same verified payer (when
    the target has a verified payer).

    Detects cycles and limits depth.

    Returns:
        List of (workspace_name, display_name, workspace_path) tuples.
    """
    workspace_names = list_workspaces()
    results: list[tuple[str, str, Path]] = []
    visited: set[str] = {target_name}

    for ws_name in workspace_names:
        if ws_name in visited:
            continue

        ws_path = get_workspace_path(ws_name)
        try:
            config = read_workspace_config(ws_path)
        except Exception:
            continue

        # Must point to our target
        if config.superseded_by != target_name:
            continue

        # Payer validation: if target has a verified payer,
        # only include workspaces with the same payer (or no payer)
        if target_payer is not None and config.aws is not None:
            ws_payer = config.aws.payer_account_id
            if ws_payer is not None and ws_payer != target_payer:
                logger.warning(
                    "Skipping linked workspace %s: payer %s != target payer %s",
                    ws_name, ws_payer, target_payer,
                )
                continue

        # Cycle detection: verify this workspace doesn't create a loop
        if _has_cycle(ws_name, visited):
            logger.warning("Cycle detected involving workspace %s, skipping", ws_name)
            continue

        visited.add(ws_name)
        display_name = config.display_name or ws_name
        results.append((ws_name, display_name, ws_path))

    return results


def _has_cycle(ws_name: str, visited: set[str]) -> bool:
    """Check if following superseded_by from ws_name creates a cycle.

    Simple depth-limited traversal — if we revisit a workspace in
    the visited set, it's a cycle.
    """
    current = ws_name
    for _ in range(_MAX_DEPTH):
        ws_path = get_workspace_path(current)
        try:
            config = read_workspace_config(ws_path)
        except Exception:
            return False

        if config.superseded_by is None:
            return False
        if config.superseded_by in visited:
            # Points back to something already in our chain
            return current != ws_name  # The first hop to target is expected
        current = config.superseded_by

    # Exceeded max depth — treat as cycle
    return True


def _read_scans(
    db_path: Path,
    limit: int = 0,
    account_id: str | None = None,
) -> list[dict[str, Any]]:
    """Read scans from a history database file (read-only).

    Opens the database in read-only mode to ensure no writes occur
    to superseded workspace databases during federated reads.

    Args:
        db_path: Path to history.db.
        limit: Max scans (0 = unlimited).
        account_id: Optional filter.

    Returns:
        List of scan dicts.
    """
    import sqlite3

    if not db_path.exists():
        return []

    try:
        # Open read-only via URI to prevent WAL modifications
        uri = f"file:{db_path}?mode=ro"
        conn = sqlite3.connect(uri, uri=True)
        conn.row_factory = sqlite3.Row

        effective_limit = limit if limit > 0 else 10000
        if account_id:
            rows = conn.execute(
                "SELECT id, timestamp, account_id, overall_score, overall_grade, "
                "total_findings, critical_findings, high_findings, duration_seconds "
                "FROM scans WHERE account_id = ? ORDER BY timestamp DESC LIMIT ?",
                (account_id, effective_limit),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT id, timestamp, account_id, overall_score, overall_grade, "
                "total_findings, critical_findings, high_findings, duration_seconds "
                "FROM scans ORDER BY timestamp DESC LIMIT ?",
                (effective_limit,),
            ).fetchall()

        result = [dict(row) for row in rows]
        conn.close()
        return result
    except Exception as e:
        logger.warning("Failed to read history from %s: %s", db_path, e)
        return []
