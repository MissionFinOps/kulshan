"""Payer-aware environment reconciliation.

Detects workspaces sharing the same verified payer account and offers
to link AWS identities into one payer workspace.

Rules:
- Never merges automatically.
- Requires explicit user confirmation.
- Preserves all existing history in old workspaces.
- Marks old workspace as superseded (not deleted).
- Updates identity registry for future routing.
- Refuses when payer evidence conflicts.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from kulshan.workspace.config import (
    AwsConnection,
    WorkspaceConfig,
    read_workspace_config,
    write_workspace_config,
)
from kulshan.workspace.paths import get_workspace_path, get_workspaces_root
from kulshan.workspace.resolution import list_workspaces

logger = logging.getLogger(__name__)


@dataclass
class PayerConflict:
    """Two or more workspaces sharing the same payer account."""

    payer_account_id: str
    workspaces: list[WorkspaceInfo] = field(default_factory=list)


@dataclass
class WorkspaceInfo:
    """Summary info about a workspace for reconciliation display."""

    name: str
    display_name: str
    payer_account_id: str | None
    connections: list[str]
    has_history: bool
    is_superseded: bool


@dataclass
class ReconcileResult:
    """Result of a reconciliation operation."""

    success: bool
    target_workspace: str
    source_workspace: str
    connection_added: str | None = None
    message: str = ""


class ReconcileError(Exception):
    """Reconciliation operation failed."""

    def __init__(self, message: str):
        super().__init__(message)


def find_payer_conflicts() -> list[PayerConflict]:
    """Scan all workspaces for shared payer accounts.

    Returns a list of PayerConflict objects, each representing a
    payer account that appears in more than one non-superseded workspace.

    Does not make AWS calls — only reads local workspace.toml files.
    """
    workspace_names = list_workspaces()
    payer_map: dict[str, list[WorkspaceInfo]] = {}

    for ws_name in workspace_names:
        ws_path = get_workspace_path(ws_name)
        try:
            config = read_workspace_config(ws_path)
        except Exception:
            continue

        # Skip unbound, superseded, or workspaces without payer
        if not config.is_bound or config.aws is None:
            continue
        if config.is_superseded:
            continue
        if config.aws.payer_account_id is None:
            continue

        payer_id = config.aws.payer_account_id
        has_history = (ws_path / "history.db").exists()

        info = WorkspaceInfo(
            name=ws_name,
            display_name=config.display_name or ws_name,
            payer_account_id=payer_id,
            connections=[c.name for c in config.aws.connections],
            has_history=has_history,
            is_superseded=config.is_superseded,
        )

        if payer_id not in payer_map:
            payer_map[payer_id] = []
        payer_map[payer_id].append(info)

    # Return only payers with multiple workspaces
    conflicts = []
    for payer_id, workspaces in payer_map.items():
        if len(workspaces) > 1:
            conflicts.append(PayerConflict(
                payer_account_id=payer_id,
                workspaces=workspaces,
            ))

    return conflicts


def find_workspaces_for_payer(payer_account_id: str) -> list[WorkspaceInfo]:
    """Find all non-superseded workspaces bound to a specific payer.

    Args:
        payer_account_id: The 12-digit payer account ID.

    Returns:
        List of WorkspaceInfo for matching workspaces.
    """
    workspace_names = list_workspaces()
    results = []

    for ws_name in workspace_names:
        ws_path = get_workspace_path(ws_name)
        try:
            config = read_workspace_config(ws_path)
        except Exception:
            continue

        if not config.is_bound or config.aws is None:
            continue
        if config.is_superseded:
            continue
        if config.aws.payer_account_id != payer_account_id:
            continue

        has_history = (ws_path / "history.db").exists()
        results.append(WorkspaceInfo(
            name=ws_name,
            display_name=config.display_name or ws_name,
            payer_account_id=payer_account_id,
            connections=[c.name for c in config.aws.connections],
            has_history=has_history,
            is_superseded=False,
        ))

    return results


def reconcile_workspace(
    source_workspace: str,
    target_workspace: str,
) -> ReconcileResult:
    """Link a source workspace's identity into a target payer workspace.

    This operation:
    1. Reads connections from the source workspace.
    2. Adds them to the target workspace (skipping duplicates).
    3. Updates the identity registry to route to the target.
    4. Marks the source workspace as superseded.
    5. Does NOT delete the source or move its history.

    Args:
        source_workspace: Directory name of workspace to supersede.
        target_workspace: Directory name of workspace to link into.

    Returns:
        ReconcileResult describing what happened.

    Raises:
        ReconcileError: If either workspace is invalid or payers conflict.
    """
    from kulshan.workspace.registry import (
        find_entry_by_workspace_dir,
        register_workspace,
        lookup_workspace_by_identity,
        list_registry_entries,
        _read_registry,
        _write_registry,
        compute_identity_key_v2,
    )

    # Load both workspaces
    source_path = get_workspace_path(source_workspace)
    target_path = get_workspace_path(target_workspace)

    if not source_path.exists() or not (source_path / "workspace.toml").exists():
        raise ReconcileError(f"Source workspace '{source_workspace}' not found.")
    if not target_path.exists() or not (target_path / "workspace.toml").exists():
        raise ReconcileError(f"Target workspace '{target_workspace}' not found.")

    source_config = read_workspace_config(source_path)
    target_config = read_workspace_config(target_path)

    # Validate both are bound
    if not source_config.is_bound or source_config.aws is None:
        raise ReconcileError(f"Source workspace '{source_workspace}' is not bound.")
    if not target_config.is_bound or target_config.aws is None:
        raise ReconcileError(f"Target workspace '{target_workspace}' is not bound.")

    # Validate payers match (or source has no payer yet)
    source_payer = source_config.aws.payer_account_id
    target_payer = target_config.aws.payer_account_id

    if source_payer is not None and target_payer is not None:
        if source_payer != target_payer:
            raise ReconcileError(
                f"Payer conflict: source has {source_payer}, "
                f"target has {target_payer}. Cannot reconcile."
            )

    # Already superseded
    if source_config.is_superseded:
        raise ReconcileError(
            f"Source workspace '{source_workspace}' is already superseded "
            f"by '{source_config.superseded_by}'."
        )

    # Add source connections to target (skip duplicates)
    existing_profiles = {
        (c.profile, c.role_arn) for c in target_config.aws.connections
    }
    added_connections = []

    for conn in source_config.aws.connections:
        key = (conn.profile, conn.role_arn)
        if key not in existing_profiles:
            # Create a new connection with a unique name
            new_name = _unique_connection_name(
                conn.name, target_config.aws.connections
            )
            new_conn = AwsConnection(
                name=new_name,
                profile=conn.profile,
                expected_session_account_id=conn.expected_session_account_id,
                role_arn=conn.role_arn,
            )
            target_config.aws.connections.append(new_conn)
            added_connections.append(new_name)

    # Write updated target config
    write_workspace_config(target_path, target_config)

    # Update registry: re-route source's identity entries to target workspace
    data = _read_registry()
    entries = data.get("entries", {})
    migrated_keys = []

    for key, entry_data in list(entries.items()):
        if entry_data.get("workspace_dir") == source_workspace:
            entry_data["workspace_dir"] = target_workspace
            migrated_keys.append(key)

    if migrated_keys:
        _write_registry(data)

    # Mark source as superseded
    source_config.superseded_by = target_workspace
    write_workspace_config(source_path, source_config)

    conn_names = ", ".join(added_connections) if added_connections else "(none new)"
    logger.info(
        "Reconciled workspace %s into %s. Connections added: %s. "
        "Registry entries migrated: %d",
        source_workspace,
        target_workspace,
        conn_names,
        len(migrated_keys),
    )

    return ReconcileResult(
        success=True,
        target_workspace=target_workspace,
        source_workspace=source_workspace,
        connection_added=added_connections[0] if added_connections else None,
        message=(
            f"Linked identity from {source_config.display_name or source_workspace} "
            f"into {target_config.display_name or target_workspace}."
        ),
    )


def _unique_connection_name(
    base_name: str,
    existing_connections: list[AwsConnection],
) -> str:
    """Generate a unique connection name avoiding duplicates."""
    existing_names = {c.name for c in existing_connections}
    if base_name not in existing_names:
        return base_name

    for i in range(2, 100):
        candidate = f"{base_name}-{i}"
        if candidate not in existing_names:
            return candidate

    # Extremely unlikely fallback
    import hashlib
    suffix = hashlib.sha256(base_name.encode()).hexdigest()[:6]
    return f"{base_name}-{suffix}"
