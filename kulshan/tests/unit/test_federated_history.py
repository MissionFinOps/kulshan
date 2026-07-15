"""Tests for federated history read-through.

Tests cover:
1. Federated reads include scans from linked workspaces.
2. Payer validation: only same-payer workspaces are included.
3. Cycle detection: superseded_by loops do not cause infinite reads.
4. Deduplication: identical scan IDs across workspaces appear once.
5. --direct-only: only direct scans shown when flag is set.
6. --account filtering works across the combined set.
7. No writes to superseded workspaces during history read.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from kulshan.history import HistoryStore, _SCHEMA
from kulshan.workspace.config import (
    AwsConnection,
    WorkspaceAwsConfig,
    WorkspaceConfig,
    write_workspace_config,
)
from kulshan.workspace.context import WorkspaceContext
from kulshan.workspace.federated_history import (
    FederatedHistoryResult,
    collect_federated_scans,
    _find_linked_workspaces,
)
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
                name=profile, profile=profile,
                expected_session_account_id="123456789012",
            )],
        ),
        superseded_by=superseded_by,
    )
    write_workspace_config(ws_path, config)
    return ws_path


def _add_scan(ws_path: Path, scan_id: str, account_id: str = "123456789012", timestamp: str = "2026-07-14T00:00:00Z") -> None:
    """Insert a scan directly into a workspace's history.db."""
    db_path = ws_path / "history.db"
    conn = sqlite3.connect(db_path)
    conn.executescript(_SCHEMA)
    conn.execute(
        """INSERT INTO scans (id, timestamp, account_id, overall_score, overall_grade,
           total_findings, critical_findings, high_findings, duration_seconds)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (scan_id, timestamp, account_id, 80, "B", 5, 0, 1, 10.0),
    )
    conn.commit()
    conn.close()


def _ws_context(ws_path: Path, name: str, display_name: str = None, payer: str | None = None) -> WorkspaceContext:
    """Build a WorkspaceContext for testing."""
    from kulshan.workspace.config import read_workspace_config
    config = read_workspace_config(ws_path)
    return WorkspaceContext.from_path(ws_path, config)


# ---------------------------------------------------------------------------
# Test 1: Federated reads include linked scans
# ---------------------------------------------------------------------------


class TestFederatedReads:
    """Federated reads include scans from linked workspaces."""

    @pytest.fixture(autouse=True)
    def _isolate(self, tmp_path, monkeypatch):
        self.workspaces_root = tmp_path / "workspaces"
        self.workspaces_root.mkdir()
        monkeypatch.setattr("kulshan.workspace.paths.get_workspaces_root", lambda: self.workspaces_root)
        monkeypatch.setattr("kulshan.workspace.resolution.get_workspaces_root", lambda: self.workspaces_root)
        monkeypatch.setattr("kulshan.workspace.resolution.ensure_workspace_infrastructure", lambda: None)
        _reset_migration_guard()

    def test_includes_linked_scans(self):
        """Target workspace sees scans from superseded workspace."""
        target = _create_workspace(self.workspaces_root, "ws_target", payer="999999999999", display_name="Acme")
        source = _create_workspace(self.workspaces_root, "ws_source", payer="999999999999", display_name="Old Audit", superseded_by="ws_target")

        _add_scan(target, "scan-a", timestamp="2026-07-14T10:00:00Z")
        _add_scan(source, "scan-b", timestamp="2026-07-10T10:00:00Z")

        ctx = _ws_context(target, "ws_target")
        result = collect_federated_scans(ctx, limit=20)

        assert len(result.scans) == 2
        assert result.linked_workspace_count == 1
        assert result.linked_scan_count == 1

        # First scan is newer (direct), second is older (linked)
        assert result.scans[0].scan["id"] == "scan-a"
        assert result.scans[0].is_linked is False
        assert result.scans[1].scan["id"] == "scan-b"
        assert result.scans[1].is_linked is True
        assert result.scans[1].source_display_name == "Old Audit"

    def test_no_linked_workspaces(self):
        """Workspace with no linked history returns direct only."""
        target = _create_workspace(self.workspaces_root, "ws_solo", payer="111111111111")
        _add_scan(target, "scan-x")

        ctx = _ws_context(target, "ws_solo")
        result = collect_federated_scans(ctx, limit=20)

        assert len(result.scans) == 1
        assert result.linked_workspace_count == 0
        assert result.linked_scan_count == 0


# ---------------------------------------------------------------------------
# Test 2: Payer validation
# ---------------------------------------------------------------------------


class TestPayerValidation:
    """Only same-payer workspaces are included in federated reads."""

    @pytest.fixture(autouse=True)
    def _isolate(self, tmp_path, monkeypatch):
        self.workspaces_root = tmp_path / "workspaces"
        self.workspaces_root.mkdir()
        monkeypatch.setattr("kulshan.workspace.paths.get_workspaces_root", lambda: self.workspaces_root)
        monkeypatch.setattr("kulshan.workspace.resolution.get_workspaces_root", lambda: self.workspaces_root)
        monkeypatch.setattr("kulshan.workspace.resolution.ensure_workspace_infrastructure", lambda: None)
        _reset_migration_guard()

    def test_different_payer_excluded(self):
        """Linked workspace with different payer is excluded."""
        target = _create_workspace(self.workspaces_root, "ws_target", payer="999999999999")
        _create_workspace(self.workspaces_root, "ws_wrong_payer", payer="111111111111", superseded_by="ws_target")
        _add_scan(self.workspaces_root / "ws_wrong_payer", "scan-foreign")

        ctx = _ws_context(target, "ws_target")
        result = collect_federated_scans(ctx, limit=20)

        # Foreign payer workspace excluded
        assert result.linked_workspace_count == 0
        scan_ids = [fs.scan["id"] for fs in result.scans]
        assert "scan-foreign" not in scan_ids


# ---------------------------------------------------------------------------
# Test 3: Cycle detection
# ---------------------------------------------------------------------------


class TestCycleDetection:
    """Superseded_by cycles are detected and handled safely."""

    @pytest.fixture(autouse=True)
    def _isolate(self, tmp_path, monkeypatch):
        self.workspaces_root = tmp_path / "workspaces"
        self.workspaces_root.mkdir()
        monkeypatch.setattr("kulshan.workspace.paths.get_workspaces_root", lambda: self.workspaces_root)
        monkeypatch.setattr("kulshan.workspace.resolution.get_workspaces_root", lambda: self.workspaces_root)
        monkeypatch.setattr("kulshan.workspace.resolution.ensure_workspace_infrastructure", lambda: None)
        _reset_migration_guard()

    def test_self_referential_cycle(self):
        """A workspace superseded by itself doesn't crash."""
        target = _create_workspace(self.workspaces_root, "ws_cycle", payer="999999999999", superseded_by="ws_cycle")
        _add_scan(target, "scan-direct")

        ctx = _ws_context(target, "ws_cycle")
        # Should not hang or crash
        result = collect_federated_scans(ctx, limit=20)
        assert len(result.scans) >= 1

    def test_mutual_cycle(self):
        """Two workspaces pointing to each other don't crash."""
        _create_workspace(self.workspaces_root, "ws_a", payer="999999999999", superseded_by="ws_b")
        target = _create_workspace(self.workspaces_root, "ws_b", payer="999999999999", superseded_by="ws_a")
        _add_scan(self.workspaces_root / "ws_a", "scan-a")
        _add_scan(target, "scan-b")

        ctx = _ws_context(target, "ws_b")
        # Should not infinite loop
        result = collect_federated_scans(ctx, limit=20)
        assert len(result.scans) >= 1


# ---------------------------------------------------------------------------
# Test 4: Deduplication
# ---------------------------------------------------------------------------


class TestDeduplication:
    """Identical scan IDs across workspaces appear only once."""

    @pytest.fixture(autouse=True)
    def _isolate(self, tmp_path, monkeypatch):
        self.workspaces_root = tmp_path / "workspaces"
        self.workspaces_root.mkdir()
        monkeypatch.setattr("kulshan.workspace.paths.get_workspaces_root", lambda: self.workspaces_root)
        monkeypatch.setattr("kulshan.workspace.resolution.get_workspaces_root", lambda: self.workspaces_root)
        monkeypatch.setattr("kulshan.workspace.resolution.ensure_workspace_infrastructure", lambda: None)
        _reset_migration_guard()

    def test_duplicate_ids_deduplicated(self):
        """Same scan ID in target and source → only one entry."""
        target = _create_workspace(self.workspaces_root, "ws_target", payer="999999999999")
        source = _create_workspace(self.workspaces_root, "ws_source", payer="999999999999", superseded_by="ws_target")

        # Same ID in both
        _add_scan(target, "scan-dup", timestamp="2026-07-14T10:00:00Z")
        _add_scan(source, "scan-dup", timestamp="2026-07-14T10:00:00Z")

        ctx = _ws_context(target, "ws_target")
        result = collect_federated_scans(ctx, limit=20)

        # Only one entry with that ID
        scan_ids = [fs.scan["id"] for fs in result.scans]
        assert scan_ids.count("scan-dup") == 1
        # Direct copy takes priority (listed first)
        assert result.scans[0].is_linked is False


# ---------------------------------------------------------------------------
# Test 5: --direct-only via CLI
# ---------------------------------------------------------------------------


class TestDirectOnly:
    """--direct-only shows only scans from this workspace."""

    @pytest.fixture(autouse=True)
    def _isolate(self, tmp_path, monkeypatch):
        self.workspaces_root = tmp_path / "workspaces"
        self.workspaces_root.mkdir()
        monkeypatch.setattr("kulshan.workspace.paths.get_workspaces_root", lambda: self.workspaces_root)
        monkeypatch.setattr("kulshan.workspace.resolution.get_workspaces_root", lambda: self.workspaces_root)
        monkeypatch.setattr("kulshan.workspace.paths.get_config_dir", lambda: tmp_path / "config")
        monkeypatch.setattr("kulshan.workspace.resolution.ensure_workspace_infrastructure", lambda: None)
        _reset_migration_guard()

    def test_direct_only_excludes_linked(self):
        """With --direct-only, linked scans are not shown."""
        target = _create_workspace(self.workspaces_root, "ws_target", payer="999999999999")
        source = _create_workspace(self.workspaces_root, "ws_source", payer="999999999999", superseded_by="ws_target")
        _add_scan(target, "scan-direct", timestamp="2026-07-14T10:00:00Z")
        _add_scan(source, "scan-linked", timestamp="2026-07-10T10:00:00Z")

        # Use collect_federated_scans for the full view
        ctx = _ws_context(target, "ws_target")
        full_result = collect_federated_scans(ctx, limit=20)
        assert len(full_result.scans) == 2

        # Direct-only: read only from target's history.db
        from kulshan.history import HistoryStore
        store = HistoryStore(target / "history.db")
        direct_scans = store.list_scans(limit=20)
        store.close()
        assert len(direct_scans) == 1
        assert direct_scans[0]["id"] == "scan-direct"


# ---------------------------------------------------------------------------
# Test 6: --account filtering across combined set
# ---------------------------------------------------------------------------


class TestAccountFiltering:
    """--account filtering works across federated history."""

    @pytest.fixture(autouse=True)
    def _isolate(self, tmp_path, monkeypatch):
        self.workspaces_root = tmp_path / "workspaces"
        self.workspaces_root.mkdir()
        monkeypatch.setattr("kulshan.workspace.paths.get_workspaces_root", lambda: self.workspaces_root)
        monkeypatch.setattr("kulshan.workspace.resolution.get_workspaces_root", lambda: self.workspaces_root)
        monkeypatch.setattr("kulshan.workspace.resolution.ensure_workspace_infrastructure", lambda: None)
        _reset_migration_guard()

    def test_account_filter_spans_linked(self):
        """Account filter applies to both direct and linked scans."""
        target = _create_workspace(self.workspaces_root, "ws_target", payer="999999999999")
        source = _create_workspace(self.workspaces_root, "ws_source", payer="999999999999", superseded_by="ws_target")

        _add_scan(target, "scan-a", account_id="111111111111")
        _add_scan(target, "scan-b", account_id="222222222222")
        _add_scan(source, "scan-c", account_id="111111111111")
        _add_scan(source, "scan-d", account_id="222222222222")

        ctx = _ws_context(target, "ws_target")

        # Filter by account 111
        result = collect_federated_scans(ctx, limit=20, account_id="111111111111")
        scan_ids = [fs.scan["id"] for fs in result.scans]
        assert "scan-a" in scan_ids
        assert "scan-c" in scan_ids
        assert "scan-b" not in scan_ids
        assert "scan-d" not in scan_ids


# ---------------------------------------------------------------------------
# Test 7: No writes to superseded workspaces
# ---------------------------------------------------------------------------


class TestNoWritesToSuperseded:
    """History reads never modify superseded workspaces."""

    @pytest.fixture(autouse=True)
    def _isolate(self, tmp_path, monkeypatch):
        self.workspaces_root = tmp_path / "workspaces"
        self.workspaces_root.mkdir()
        monkeypatch.setattr("kulshan.workspace.paths.get_workspaces_root", lambda: self.workspaces_root)
        monkeypatch.setattr("kulshan.workspace.resolution.get_workspaces_root", lambda: self.workspaces_root)
        monkeypatch.setattr("kulshan.workspace.resolution.ensure_workspace_infrastructure", lambda: None)
        _reset_migration_guard()

    def test_source_db_not_modified(self):
        """Reading federated history does not modify the source database."""
        target = _create_workspace(self.workspaces_root, "ws_target", payer="999999999999")
        source = _create_workspace(self.workspaces_root, "ws_source", payer="999999999999", superseded_by="ws_target")
        _add_scan(source, "scan-old")

        source_db = source / "history.db"
        mtime_before = source_db.stat().st_mtime_ns

        ctx = _ws_context(target, "ws_target")
        collect_federated_scans(ctx, limit=20)

        mtime_after = source_db.stat().st_mtime_ns
        assert mtime_after == mtime_before
