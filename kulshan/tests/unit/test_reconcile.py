"""Tests for payer-aware environment reconciliation.

Tests cover:
1. Detection: find_payer_conflicts identifies shared payers.
2. Linking: reconcile_workspace adds connections to target.
3. Registry update: identity routing moves to target workspace.
4. Superseded marking: source workspace marked superseded.
5. Refusal on conflict: mismatched payers are rejected.
6. History preservation: source workspace and history.db untouched.
7. No automatic merge: reconciliation requires explicit call.
8. Duplicate connections skipped: same profile+role not added twice.
9. CLI command works with mocked workspace data.
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from kulshan.workspace.config import (
    AwsConnection,
    WorkspaceAwsConfig,
    WorkspaceConfig,
    read_workspace_config,
    write_workspace_config,
)
from kulshan.workspace.reconcile import (
    PayerConflict,
    ReconcileError,
    ReconcileResult,
    WorkspaceInfo,
    find_payer_conflicts,
    find_workspaces_for_payer,
    reconcile_workspace,
)
from kulshan.workspace.registry import register_workspace, _read_registry
from kulshan.workspace.resolution import _reset_migration_guard


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _create_workspace(
    workspaces_root: Path,
    name: str,
    payer: str | None = None,
    display_name: str | None = None,
    profile: str = "test",
    account_id: str = "123456789012",
    role_arn: str | None = None,
    with_history: bool = False,
    superseded_by: str | None = None,
) -> Path:
    """Create a workspace directory with config."""
    ws_path = workspaces_root / name
    ws_path.mkdir(parents=True, exist_ok=True)
    config = WorkspaceConfig(
        name=name,
        display_name=display_name or name,
        binding_mode="bound",
        aws=WorkspaceAwsConfig(
            payer_account_id=payer,
            default_connection=profile,
            connections=[AwsConnection(
                name=profile,
                profile=profile,
                expected_session_account_id=account_id,
                role_arn=role_arn,
            )],
        ),
        superseded_by=superseded_by,
    )
    write_workspace_config(ws_path, config)
    if with_history:
        (ws_path / "history.db").write_text("fake-history")
    return ws_path


# ---------------------------------------------------------------------------
# Test 1: Detection
# ---------------------------------------------------------------------------


class TestFindPayerConflicts:
    """find_payer_conflicts identifies shared payers."""

    @pytest.fixture(autouse=True)
    def _isolate(self, tmp_path, monkeypatch):
        self.workspaces_root = tmp_path / "workspaces"
        self.workspaces_root.mkdir()
        monkeypatch.setattr(
            "kulshan.workspace.paths.get_workspaces_root",
            lambda: self.workspaces_root,
        )
        monkeypatch.setattr(
            "kulshan.workspace.resolution.get_workspaces_root",
            lambda: self.workspaces_root,
        )
        monkeypatch.setattr(
            "kulshan.workspace.resolution.ensure_workspace_infrastructure",
            lambda: None,
        )
        _reset_migration_guard()

    def test_no_conflicts(self):
        """Unique payers → no conflicts."""
        _create_workspace(self.workspaces_root, "ws_a", payer="111111111111")
        _create_workspace(self.workspaces_root, "ws_b", payer="222222222222")
        assert find_payer_conflicts() == []

    def test_shared_payer_detected(self):
        """Two workspaces with same payer → one conflict."""
        _create_workspace(self.workspaces_root, "ws_a", payer="999999999999", profile="role-a")
        _create_workspace(self.workspaces_root, "ws_b", payer="999999999999", profile="role-b")

        conflicts = find_payer_conflicts()
        assert len(conflicts) == 1
        assert conflicts[0].payer_account_id == "999999999999"
        assert len(conflicts[0].workspaces) == 2

    def test_superseded_excluded(self):
        """Superseded workspaces are excluded from conflict detection."""
        _create_workspace(self.workspaces_root, "ws_a", payer="999999999999")
        _create_workspace(
            self.workspaces_root, "ws_b", payer="999999999999",
            superseded_by="ws_a",
        )
        assert find_payer_conflicts() == []

    def test_unverified_payer_excluded(self):
        """Workspaces with no payer (None) are excluded."""
        _create_workspace(self.workspaces_root, "ws_a", payer="999999999999")
        _create_workspace(self.workspaces_root, "ws_b", payer=None)
        assert find_payer_conflicts() == []


# ---------------------------------------------------------------------------
# Test 2: Linking
# ---------------------------------------------------------------------------


class TestReconcileWorkspace:
    """reconcile_workspace adds connections to target."""

    @pytest.fixture(autouse=True)
    def _isolate(self, tmp_path, monkeypatch):
        self.tmp_path = tmp_path
        self.workspaces_root = tmp_path / "workspaces"
        self.workspaces_root.mkdir()
        monkeypatch.setattr(
            "kulshan.workspace.paths.get_workspaces_root",
            lambda: self.workspaces_root,
        )
        monkeypatch.setattr(
            "kulshan.workspace.registry.get_data_dir",
            lambda: tmp_path,
        )
        _reset_migration_guard()

    def test_connection_added_to_target(self):
        """Source connection is added to target workspace."""
        _create_workspace(
            self.workspaces_root, "ws_target",
            payer="999999999999", profile="role-a", account_id="111111111111",
        )
        _create_workspace(
            self.workspaces_root, "ws_source",
            payer="999999999999", profile="role-b", account_id="222222222222",
        )

        result = reconcile_workspace("ws_source", "ws_target")
        assert result.success is True
        assert result.connection_added == "role-b"

        # Verify target now has two connections
        target_config = read_workspace_config(self.workspaces_root / "ws_target")
        assert len(target_config.aws.connections) == 2
        conn_names = [c.name for c in target_config.aws.connections]
        assert "role-a" in conn_names
        assert "role-b" in conn_names

    def test_duplicate_connection_skipped(self):
        """Same profile+role already in target → not added again."""
        _create_workspace(
            self.workspaces_root, "ws_target",
            payer="999999999999", profile="shared-role",
        )
        _create_workspace(
            self.workspaces_root, "ws_source",
            payer="999999999999", profile="shared-role",
        )

        result = reconcile_workspace("ws_source", "ws_target")
        assert result.success is True
        assert result.connection_added is None  # No new connection

        target_config = read_workspace_config(self.workspaces_root / "ws_target")
        assert len(target_config.aws.connections) == 1


# ---------------------------------------------------------------------------
# Test 3: Registry update
# ---------------------------------------------------------------------------


class TestRegistryUpdate:
    """Identity routing moves to target workspace after reconciliation."""

    @pytest.fixture(autouse=True)
    def _isolate(self, tmp_path, monkeypatch):
        self.tmp_path = tmp_path
        self.workspaces_root = tmp_path / "workspaces"
        self.workspaces_root.mkdir()
        monkeypatch.setattr(
            "kulshan.workspace.paths.get_workspaces_root",
            lambda: self.workspaces_root,
        )
        monkeypatch.setattr(
            "kulshan.workspace.registry.get_data_dir",
            lambda: tmp_path,
        )
        _reset_migration_guard()

    def test_registry_entries_migrated(self):
        """Registry entries for source now point to target."""
        _create_workspace(
            self.workspaces_root, "ws_target",
            payer="999999999999", profile="role-a",
        )
        _create_workspace(
            self.workspaces_root, "ws_source",
            payer="999999999999", profile="role-b",
        )
        # Register source in the registry
        register_workspace(
            profile="role-b", role_arn=None, account_id="222222222222",
            workspace_dir="ws_source", display_name="source-oak",
            created_at="2025-01-01T00:00:00Z",
            arn="arn:aws:iam::222222222222:role/RoleB",
        )

        reconcile_workspace("ws_source", "ws_target")

        # Verify registry now points to target
        reg_data = _read_registry()
        for entry_data in reg_data.get("entries", {}).values():
            if entry_data.get("account_id") == "222222222222":
                assert entry_data["workspace_dir"] == "ws_target"


# ---------------------------------------------------------------------------
# Test 4: Superseded marking
# ---------------------------------------------------------------------------


class TestSupersededMarking:
    """Source workspace is marked superseded."""

    @pytest.fixture(autouse=True)
    def _isolate(self, tmp_path, monkeypatch):
        self.workspaces_root = tmp_path / "workspaces"
        self.workspaces_root.mkdir()
        monkeypatch.setattr(
            "kulshan.workspace.paths.get_workspaces_root",
            lambda: self.workspaces_root,
        )
        monkeypatch.setattr(
            "kulshan.workspace.registry.get_data_dir",
            lambda: tmp_path,
        )
        _reset_migration_guard()

    def test_source_marked_superseded(self):
        """After reconciliation, source has superseded_by set."""
        _create_workspace(self.workspaces_root, "ws_target", payer="999999999999")
        _create_workspace(self.workspaces_root, "ws_source", payer="999999999999", profile="other")

        reconcile_workspace("ws_source", "ws_target")

        source_config = read_workspace_config(self.workspaces_root / "ws_source")
        assert source_config.superseded_by == "ws_target"
        assert source_config.is_superseded is True

    def test_already_superseded_rejected(self):
        """Cannot reconcile an already-superseded workspace."""
        _create_workspace(self.workspaces_root, "ws_target", payer="999999999999")
        _create_workspace(
            self.workspaces_root, "ws_source", payer="999999999999",
            profile="other", superseded_by="ws_something",
        )

        with pytest.raises(ReconcileError, match="already superseded"):
            reconcile_workspace("ws_source", "ws_target")


# ---------------------------------------------------------------------------
# Test 5: Refusal on conflict
# ---------------------------------------------------------------------------


class TestRefusalOnConflict:
    """Mismatched payers are rejected."""

    @pytest.fixture(autouse=True)
    def _isolate(self, tmp_path, monkeypatch):
        self.workspaces_root = tmp_path / "workspaces"
        self.workspaces_root.mkdir()
        monkeypatch.setattr(
            "kulshan.workspace.paths.get_workspaces_root",
            lambda: self.workspaces_root,
        )
        monkeypatch.setattr(
            "kulshan.workspace.registry.get_data_dir",
            lambda: tmp_path,
        )
        _reset_migration_guard()

    def test_payer_mismatch_rejected(self):
        """Source payer 111 vs target payer 222 → ReconcileError."""
        _create_workspace(
            self.workspaces_root, "ws_target", payer="222222222222"
        )
        _create_workspace(
            self.workspaces_root, "ws_source", payer="111111111111", profile="x"
        )

        with pytest.raises(ReconcileError, match="Payer conflict"):
            reconcile_workspace("ws_source", "ws_target")


# ---------------------------------------------------------------------------
# Test 6: History preservation
# ---------------------------------------------------------------------------


class TestHistoryPreservation:
    """Source workspace and its history.db remain untouched."""

    @pytest.fixture(autouse=True)
    def _isolate(self, tmp_path, monkeypatch):
        self.workspaces_root = tmp_path / "workspaces"
        self.workspaces_root.mkdir()
        monkeypatch.setattr(
            "kulshan.workspace.paths.get_workspaces_root",
            lambda: self.workspaces_root,
        )
        monkeypatch.setattr(
            "kulshan.workspace.registry.get_data_dir",
            lambda: tmp_path,
        )
        _reset_migration_guard()

    def test_source_history_preserved(self):
        """history.db in source workspace is never deleted or moved."""
        _create_workspace(
            self.workspaces_root, "ws_target", payer="999999999999"
        )
        source_path = _create_workspace(
            self.workspaces_root, "ws_source", payer="999999999999",
            profile="other", with_history=True,
        )

        # Verify history exists before
        assert (source_path / "history.db").exists()

        reconcile_workspace("ws_source", "ws_target")

        # Verify history still exists after
        assert (source_path / "history.db").exists()
        assert (source_path / "history.db").read_text() == "fake-history"

        # Source directory still exists
        assert source_path.exists()
        assert (source_path / "workspace.toml").exists()


# ---------------------------------------------------------------------------
# Test 7: No automatic merge
# ---------------------------------------------------------------------------


class TestNoAutomaticMerge:
    """Reconciliation requires explicit call — never happens automatically."""

    @pytest.fixture(autouse=True)
    def _isolate(self, tmp_path, monkeypatch):
        self.workspaces_root = tmp_path / "workspaces"
        self.workspaces_root.mkdir()
        monkeypatch.setattr(
            "kulshan.workspace.paths.get_workspaces_root",
            lambda: self.workspaces_root,
        )
        monkeypatch.setattr(
            "kulshan.workspace.resolution.get_workspaces_root",
            lambda: self.workspaces_root,
        )
        monkeypatch.setattr(
            "kulshan.workspace.resolution.ensure_workspace_infrastructure",
            lambda: None,
        )
        _reset_migration_guard()

    def test_find_conflicts_does_not_reconcile(self):
        """find_payer_conflicts only detects, never modifies."""
        _create_workspace(self.workspaces_root, "ws_a", payer="999999999999", profile="a")
        _create_workspace(self.workspaces_root, "ws_b", payer="999999999999", profile="b")

        # Detection only
        conflicts = find_payer_conflicts()
        assert len(conflicts) == 1

        # Neither workspace is superseded
        config_a = read_workspace_config(self.workspaces_root / "ws_a")
        config_b = read_workspace_config(self.workspaces_root / "ws_b")
        assert config_a.superseded_by is None
        assert config_b.superseded_by is None

        # Both still have exactly one connection
        assert len(config_a.aws.connections) == 1
        assert len(config_b.aws.connections) == 1


# ---------------------------------------------------------------------------
# Test 8: CLI command
# ---------------------------------------------------------------------------


class TestReconcileCli:
    """workspace reconcile CLI command works."""

    @pytest.fixture(autouse=True)
    def _isolate(self, tmp_path, monkeypatch):
        self.workspaces_root = tmp_path / "workspaces"
        self.workspaces_root.mkdir()
        monkeypatch.setattr(
            "kulshan.workspace.paths.get_workspaces_root",
            lambda: self.workspaces_root,
        )
        monkeypatch.setattr(
            "kulshan.workspace.resolution.get_workspaces_root",
            lambda: self.workspaces_root,
        )
        monkeypatch.setattr(
            "kulshan.workspace.paths.get_data_dir",
            lambda: tmp_path,
        )
        monkeypatch.setattr(
            "kulshan.workspace.registry.get_data_dir",
            lambda: tmp_path,
        )
        monkeypatch.setattr(
            "kulshan.workspace.resolution.ensure_workspace_infrastructure",
            lambda: None,
        )
        _reset_migration_guard()

    def test_no_conflicts_message(self):
        """No conflicts → clean message."""
        from click.testing import CliRunner
        from kulshan.workspace.cli import workspace

        _create_workspace(self.workspaces_root, "ws_a", payer="111111111111")

        runner = CliRunner()
        result = runner.invoke(workspace, ["reconcile"])
        assert result.exit_code == 0
        assert "No payer conflicts" in result.output

    def test_conflict_shown(self):
        """Conflict is displayed with workspace details."""
        from click.testing import CliRunner
        from kulshan.workspace.cli import workspace

        _create_workspace(
            self.workspaces_root, "ws_a", payer="999999999999",
            display_name="Acme Corp", profile="admin",
        )
        _create_workspace(
            self.workspaces_root, "ws_b", payer="999999999999",
            display_name="Acme Audit", profile="audit",
        )

        runner = CliRunner()
        # Decline the reconciliation
        result = runner.invoke(workspace, ["reconcile"], input="n\n")
        assert result.exit_code == 0
        assert "Acme Corp" in result.output
        assert "Acme Audit" in result.output
        assert "Skipped" in result.output
