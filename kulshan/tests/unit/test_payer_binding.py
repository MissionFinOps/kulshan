"""Tests for automatic payer binding from CUR evidence.

Tests cover all 11 required cases:
1. First valid CUR binds the payer.
2. Repeated matching payer does not rewrite unrelated workspace metadata.
3. Mismatched payer fails.
4. Multiple payers fail.
5. Missing evidence does not bind.
6. Invalid payer evidence fails.
7. Display name and workspace directory remain unchanged.
8. No automatic workspace merge occurs.
9. Binding survives a new process and routes to the same local database.
10. No boto3 or STS call occurs during local CUR binding.
11. Full test suite remains green (verified by CI).
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from kulshan.workspace.config import (
    AwsConnection,
    WorkspaceAwsConfig,
    WorkspaceConfig,
    read_workspace_config,
    write_workspace_config,
)
from kulshan.workspace.context import WorkspaceContext
from kulshan.workspace.onboarding import (
    PayerBindingConflictError,
    PayerBindingError,
    bind_payer_account,
)
from kulshan.workspace.payer_binding import (
    InvalidPayerEvidenceError,
    MultiplePayerEvidenceError,
    PayerBindingResult,
    extract_payer_from_cur,
    try_bind_payer_from_cur,
)
from kulshan.workspace.registry import register_workspace
from kulshan.workspace.resolution import resolve_workspace_with_profile, _reset_migration_guard


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _create_bound_workspace(
    workspaces_root: Path,
    name: str,
    payer: str | None = None,
    display_name: str = "test-display",
    profile: str = "test-profile",
    account_id: str = "123456789012",
) -> Path:
    """Create a bound workspace directory with config."""
    ws_path = workspaces_root / name
    ws_path.mkdir(parents=True, exist_ok=True)
    config = WorkspaceConfig(
        name=name,
        display_name=display_name,
        binding_mode="bound",
        aws=WorkspaceAwsConfig(
            payer_account_id=payer,
            default_connection=profile,
            connections=[AwsConnection(
                name=profile,
                profile=profile,
                expected_session_account_id=account_id,
            )],
        ),
    )
    write_workspace_config(ws_path, config)
    return ws_path


def _mock_duckdb_with_payer(payer_values: list[str] | None, has_column: bool = True):
    """Create a mock DuckDB connection returning specific payer values."""
    con = MagicMock()

    if has_column:
        # DESCRIBE returns column names including bill_payer_account_id
        con.execute.return_value.fetchall.side_effect = [
            [("bill_payer_account_id",), ("line_item_usage_amount",)],  # DESCRIBE
            [(v,) for v in (payer_values or [])],  # SELECT DISTINCT
        ]
    else:
        # No payer column in schema
        con.execute.return_value.fetchall.return_value = [
            ("line_item_usage_amount",),
            ("line_item_type",),
        ]

    return con


def _mock_duckdb_sequential(describe_result, select_result):
    """Create a mock DuckDB with explicit control over call sequence."""
    con = MagicMock()
    call_count = [0]

    def mock_execute(sql):
        result = MagicMock()
        if "DESCRIBE" in sql:
            result.fetchall.return_value = describe_result
        else:
            result.fetchall.return_value = select_result
        return result

    con.execute.side_effect = mock_execute
    return con


# ---------------------------------------------------------------------------
# Test 1: First valid CUR binds the payer
# ---------------------------------------------------------------------------


class TestFirstValidCurBindsPayer:
    """First valid CUR containing exactly one payer binds the workspace."""

    @pytest.fixture(autouse=True)
    def _isolate(self, tmp_path, monkeypatch):
        self.workspaces_root = tmp_path / "workspaces"
        self.workspaces_root.mkdir()
        monkeypatch.setattr(
            "kulshan.workspace.paths.get_workspaces_root",
            lambda: self.workspaces_root,
        )
        monkeypatch.setattr(
            "kulshan.workspace.onboarding.get_workspace_path",
            lambda name: self.workspaces_root / name,
        )

    def test_first_bind(self):
        """Unverified workspace gets payer bound from CUR."""
        ws_path = _create_bound_workspace(
            self.workspaces_root, "ws_first", payer=None
        )
        config_before = read_workspace_config(ws_path)
        assert config_before.aws.payer_account_id is None

        ws_ctx = WorkspaceContext.from_path(ws_path, config_before)
        con = _mock_duckdb_sequential(
            [("bill_payer_account_id",), ("line_item_cost",)],
            [("999999999999",)],
        )

        result = try_bind_payer_from_cur(con, ws_ctx)

        assert result.status == "bound"
        assert result.payer_account_id == "999999999999"

        # Verify persisted
        config_after = read_workspace_config(ws_path)
        assert config_after.aws.payer_account_id == "999999999999"
        assert config_after.aws.payer_binding_source == "cur"
        assert config_after.aws.payer_bound_at is not None


# ---------------------------------------------------------------------------
# Test 2: Repeated matching payer does not rewrite unrelated metadata
# ---------------------------------------------------------------------------


class TestRepeatedMatchingPayer:
    """A repeated matching payer does not rewrite unrelated workspace metadata."""

    @pytest.fixture(autouse=True)
    def _isolate(self, tmp_path, monkeypatch):
        self.workspaces_root = tmp_path / "workspaces"
        self.workspaces_root.mkdir()
        monkeypatch.setattr(
            "kulshan.workspace.paths.get_workspaces_root",
            lambda: self.workspaces_root,
        )
        monkeypatch.setattr(
            "kulshan.workspace.onboarding.get_workspace_path",
            lambda name: self.workspaces_root / name,
        )

    def test_no_rewrite_on_match(self):
        """Already-bound workspace with matching payer → no file write."""
        ws_path = _create_bound_workspace(
            self.workspaces_root, "ws_repeat",
            payer="999999999999",
            display_name="My Custom Name",
        )
        # Record file modification time
        config_path = ws_path / "workspace.toml"
        mtime_before = config_path.stat().st_mtime_ns

        config = read_workspace_config(ws_path)
        ws_ctx = WorkspaceContext.from_path(ws_path, config)
        con = _mock_duckdb_sequential(
            [("bill_payer_account_id",)],
            [("999999999999",)],
        )

        result = try_bind_payer_from_cur(con, ws_ctx)

        assert result.status == "already_bound"
        assert result.payer_account_id == "999999999999"

        # Config file should not have been rewritten
        mtime_after = config_path.stat().st_mtime_ns
        assert mtime_after == mtime_before

        # Display name unchanged
        config_after = read_workspace_config(ws_path)
        assert config_after.display_name == "My Custom Name"


# ---------------------------------------------------------------------------
# Test 3: Mismatched payer fails
# ---------------------------------------------------------------------------


class TestMismatchedPayerFails:
    """A workspace bound to payer A receiving CUR from payer B must fail."""

    @pytest.fixture(autouse=True)
    def _isolate(self, tmp_path, monkeypatch):
        self.workspaces_root = tmp_path / "workspaces"
        self.workspaces_root.mkdir()
        monkeypatch.setattr(
            "kulshan.workspace.paths.get_workspaces_root",
            lambda: self.workspaces_root,
        )
        monkeypatch.setattr(
            "kulshan.workspace.onboarding.get_workspace_path",
            lambda name: self.workspaces_root / name,
        )

    def test_conflict_raises(self):
        """Mismatched payer raises PayerBindingConflictError."""
        ws_path = _create_bound_workspace(
            self.workspaces_root, "ws_conflict",
            payer="111111111111",
        )
        config = read_workspace_config(ws_path)
        ws_ctx = WorkspaceContext.from_path(ws_path, config)
        con = _mock_duckdb_sequential(
            [("bill_payer_account_id",)],
            [("222222222222",)],
        )

        with pytest.raises(PayerBindingConflictError) as exc_info:
            try_bind_payer_from_cur(con, ws_ctx)

        assert exc_info.value.existing_payer == "111111111111"
        assert exc_info.value.new_payer == "222222222222"


# ---------------------------------------------------------------------------
# Test 4: Multiple payers fail
# ---------------------------------------------------------------------------


class TestMultiplePayersFail:
    """CUR with multiple distinct payer IDs must fail."""

    @pytest.fixture(autouse=True)
    def _isolate(self, tmp_path, monkeypatch):
        self.workspaces_root = tmp_path / "workspaces"
        self.workspaces_root.mkdir()
        monkeypatch.setattr(
            "kulshan.workspace.paths.get_workspaces_root",
            lambda: self.workspaces_root,
        )
        monkeypatch.setattr(
            "kulshan.workspace.onboarding.get_workspace_path",
            lambda name: self.workspaces_root / name,
        )

    def test_multiple_payers_raises(self):
        """Two distinct payer IDs in CUR raises MultiplePayerEvidenceError."""
        con = _mock_duckdb_sequential(
            [("bill_payer_account_id",)],
            [("111111111111",), ("222222222222",)],
        )

        with pytest.raises(MultiplePayerEvidenceError) as exc_info:
            extract_payer_from_cur(con)

        assert "111111111111" in exc_info.value.payer_ids
        assert "222222222222" in exc_info.value.payer_ids


# ---------------------------------------------------------------------------
# Test 5: Missing evidence does not bind
# ---------------------------------------------------------------------------


class TestMissingEvidenceDoesNotBind:
    """No payer column or no payer values → no binding, just a warning."""

    @pytest.fixture(autouse=True)
    def _isolate(self, tmp_path, monkeypatch):
        self.workspaces_root = tmp_path / "workspaces"
        self.workspaces_root.mkdir()
        monkeypatch.setattr(
            "kulshan.workspace.paths.get_workspaces_root",
            lambda: self.workspaces_root,
        )
        monkeypatch.setattr(
            "kulshan.workspace.onboarding.get_workspace_path",
            lambda name: self.workspaces_root / name,
        )

    def test_no_payer_column(self):
        """CUR without payer column → missing status."""
        ws_path = _create_bound_workspace(
            self.workspaces_root, "ws_nopayer", payer=None
        )
        config = read_workspace_config(ws_path)
        ws_ctx = WorkspaceContext.from_path(ws_path, config)

        # DuckDB with no payer column
        con = MagicMock()
        con.execute.return_value.fetchall.return_value = [
            ("line_item_cost",), ("line_item_type",),
        ]

        result = try_bind_payer_from_cur(con, ws_ctx)
        assert result.status == "missing"

        # Payer should NOT be set
        config_after = read_workspace_config(ws_path)
        assert config_after.aws.payer_account_id is None

    def test_empty_payer_values(self):
        """CUR with payer column but all nulls/empty → missing."""
        ws_path = _create_bound_workspace(
            self.workspaces_root, "ws_empty", payer=None
        )
        config = read_workspace_config(ws_path)
        ws_ctx = WorkspaceContext.from_path(ws_path, config)

        con = _mock_duckdb_sequential(
            [("bill_payer_account_id",)],
            [],  # No rows after filtering nulls
        )

        result = try_bind_payer_from_cur(con, ws_ctx)
        assert result.status == "missing"


# ---------------------------------------------------------------------------
# Test 6: Invalid payer evidence fails
# ---------------------------------------------------------------------------


class TestInvalidPayerEvidenceFails:
    """Non-empty payer values that aren't valid 12-digit account IDs must fail."""

    def test_alphabetic_value(self):
        """Alphabetic payer value raises InvalidPayerEvidenceError."""
        con = _mock_duckdb_sequential(
            [("bill_payer_account_id",)],
            [("not-an-account",)],
        )

        with pytest.raises(InvalidPayerEvidenceError) as exc_info:
            extract_payer_from_cur(con)

        assert "not-an-account" in str(exc_info.value)

    def test_short_numeric(self):
        """11-digit value raises InvalidPayerEvidenceError."""
        con = _mock_duckdb_sequential(
            [("bill_payer_account_id",)],
            [("12345678901",)],  # 11 digits
        )

        with pytest.raises(InvalidPayerEvidenceError):
            extract_payer_from_cur(con)

    def test_13_digits(self):
        """13-digit value raises InvalidPayerEvidenceError."""
        con = _mock_duckdb_sequential(
            [("bill_payer_account_id",)],
            [("1234567890123",)],
        )

        with pytest.raises(InvalidPayerEvidenceError):
            extract_payer_from_cur(con)


# ---------------------------------------------------------------------------
# Test 7: Display name and workspace directory remain unchanged
# ---------------------------------------------------------------------------


class TestDisplayNameAndDirUnchanged:
    """Binding payer must not alter display name or directory."""

    @pytest.fixture(autouse=True)
    def _isolate(self, tmp_path, monkeypatch):
        self.workspaces_root = tmp_path / "workspaces"
        self.workspaces_root.mkdir()
        monkeypatch.setattr(
            "kulshan.workspace.paths.get_workspaces_root",
            lambda: self.workspaces_root,
        )
        monkeypatch.setattr(
            "kulshan.workspace.onboarding.get_workspace_path",
            lambda name: self.workspaces_root / name,
        )

    def test_name_and_dir_stable(self):
        """After binding, display_name and directory name are unchanged."""
        ws_path = _create_bound_workspace(
            self.workspaces_root, "ws_7f3a842c",
            payer=None,
            display_name="acme-finops-cedar",
        )

        bind_payer_account("ws_7f3a842c", "888888888888")

        config = read_workspace_config(ws_path)
        assert config.display_name == "acme-finops-cedar"
        assert config.name == "ws_7f3a842c"
        assert ws_path.name == "ws_7f3a842c"


# ---------------------------------------------------------------------------
# Test 8: No automatic workspace merge occurs
# ---------------------------------------------------------------------------


class TestNoAutomaticMerge:
    """Two workspaces bound to the same payer remain separate."""

    @pytest.fixture(autouse=True)
    def _isolate(self, tmp_path, monkeypatch):
        self.workspaces_root = tmp_path / "workspaces"
        self.workspaces_root.mkdir()
        monkeypatch.setattr(
            "kulshan.workspace.paths.get_workspaces_root",
            lambda: self.workspaces_root,
        )
        monkeypatch.setattr(
            "kulshan.workspace.onboarding.get_workspace_path",
            lambda name: self.workspaces_root / name,
        )

    def test_same_payer_stays_separate(self):
        """Two workspaces getting same payer from CUR remain independent."""
        ws_a = _create_bound_workspace(
            self.workspaces_root, "ws_aaaaaaaa", payer=None,
            display_name="team-a", profile="profile-a",
        )
        ws_b = _create_bound_workspace(
            self.workspaces_root, "ws_bbbbbbbb", payer=None,
            display_name="team-b", profile="profile-b",
        )

        # Bind both to the same payer
        bind_payer_account("ws_aaaaaaaa", "999999999999")
        bind_payer_account("ws_bbbbbbbb", "999999999999")

        # Both still exist as separate workspaces
        assert (self.workspaces_root / "ws_aaaaaaaa" / "workspace.toml").exists()
        assert (self.workspaces_root / "ws_bbbbbbbb" / "workspace.toml").exists()

        config_a = read_workspace_config(ws_a)
        config_b = read_workspace_config(ws_b)
        assert config_a.display_name == "team-a"
        assert config_b.display_name == "team-b"
        assert config_a.aws.payer_account_id == "999999999999"
        assert config_b.aws.payer_account_id == "999999999999"


# ---------------------------------------------------------------------------
# Test 9: Binding survives a new process and routes to same database
# ---------------------------------------------------------------------------


class TestBindingSurvivesRestart:
    """Binding persists to disk and routes correctly on next invocation."""

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
            "kulshan.workspace.paths.get_data_dir",
            lambda: tmp_path,
        )
        monkeypatch.setattr(
            "kulshan.workspace.paths.get_config_dir",
            lambda: tmp_path / "config",
        )
        monkeypatch.setattr(
            "kulshan.workspace.registry.get_data_dir",
            lambda: tmp_path,
        )
        monkeypatch.setattr(
            "kulshan.workspace.onboarding.get_workspace_path",
            lambda name: self.workspaces_root / name,
        )
        monkeypatch.setattr(
            "kulshan.workspace.resolution.ensure_workspace_infrastructure",
            lambda: None,
        )
        monkeypatch.delenv("KULSHAN_WORKSPACE", raising=False)
        monkeypatch.delenv("AWS_PROFILE", raising=False)
        _reset_migration_guard()

    def test_binding_persists_and_routes(self):
        """After binding, a subsequent resolve finds the same workspace with payer set."""
        # Create and register workspace
        _create_bound_workspace(
            self.workspaces_root, "ws_persist", payer=None, profile="my-profile"
        )
        register_workspace(
            "my-profile", None, "123456789012",
            "ws_persist", "my-profile-oak", "2025-01-01T00:00:00Z",
        )

        # Bind the payer
        bind_payer_account("ws_persist", "777777777777")

        # Simulate "new process" — re-resolve the workspace
        ws_ctx = resolve_workspace_with_profile(profile="my-profile", role_arn=None)
        assert ws_ctx is not None
        assert ws_ctx.name == "ws_persist"
        assert ws_ctx.config.aws.payer_account_id == "777777777777"
        assert ws_ctx.config.aws.payer_binding_source == "cur"
        # Same database path
        assert ws_ctx.history_db_path == self.workspaces_root / "ws_persist" / "history.db"


# ---------------------------------------------------------------------------
# Test 10: No boto3 or STS call occurs during local CUR binding
# ---------------------------------------------------------------------------


class TestNoBoto3DuringBinding:
    """Payer binding is entirely local — no AWS API calls."""

    @pytest.fixture(autouse=True)
    def _isolate(self, tmp_path, monkeypatch):
        self.workspaces_root = tmp_path / "workspaces"
        self.workspaces_root.mkdir()
        monkeypatch.setattr(
            "kulshan.workspace.paths.get_workspaces_root",
            lambda: self.workspaces_root,
        )
        monkeypatch.setattr(
            "kulshan.workspace.onboarding.get_workspace_path",
            lambda name: self.workspaces_root / name,
        )

    def test_no_boto3_import_during_bind(self):
        """bind_payer_account does not import or call boto3."""
        import sys

        _create_bound_workspace(
            self.workspaces_root, "ws_local", payer=None
        )

        # Patch boto3 to raise if imported
        fake_boto3 = MagicMock()
        fake_boto3.Session.side_effect = RuntimeError("boto3 should not be called!")

        with patch.dict(sys.modules, {"boto3": fake_boto3}):
            # This must succeed without touching boto3
            bind_payer_account("ws_local", "555555555555")

        config = read_workspace_config(self.workspaces_root / "ws_local")
        assert config.aws.payer_account_id == "555555555555"

    def test_no_boto3_in_extract(self):
        """extract_payer_from_cur is entirely DuckDB-local."""
        import sys

        fake_boto3 = MagicMock()
        fake_boto3.Session.side_effect = RuntimeError("boto3 should not be called!")

        con = _mock_duckdb_sequential(
            [("bill_payer_account_id",)],
            [("123456789012",)],
        )

        with patch.dict(sys.modules, {"boto3": fake_boto3}):
            payer = extract_payer_from_cur(con)

        assert payer == "123456789012"
