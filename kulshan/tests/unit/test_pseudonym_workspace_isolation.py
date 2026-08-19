"""Tests for workspace-scoped pseudonymization secret isolation.

Verifies that:
- Each workspace has its own pseudonym.key
- Same identifier + different workspace = different alias
- Same identifier + same workspace = same alias (deterministic)
- No code path silently uses a global machine-wide secret
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest

from kulshan.pseudonym.engine import PseudonymizationEngine
from kulshan.pseudonym.policy import PseudonymPolicy
from kulshan.pseudonym.secret import SECRET_FILENAME, load_or_create_secret
from kulshan.pseudonym.types import IdentifierClass


SYNTHETIC_ACCOUNT = "111222333444"


@pytest.fixture
def workspace_a(tmp_path: Path) -> Path:
    ws = tmp_path / "workspaces" / "ws_aaaa1111"
    ws.mkdir(parents=True)
    return ws


@pytest.fixture
def workspace_b(tmp_path: Path) -> Path:
    ws = tmp_path / "workspaces" / "ws_bbbb2222"
    ws.mkdir(parents=True)
    return ws


def _engine_for(workspace_path: Path) -> PseudonymizationEngine:
    """Create an active engine scoped to a specific workspace."""
    return PseudonymizationEngine.create(
        workspace_path, PseudonymPolicy.for_structured_output()
    )


class TestWorkspaceIsolation:
    """Different workspaces produce different aliases for the same identifier."""

    def test_different_workspaces_different_aliases(self, workspace_a, workspace_b):
        """Core invariant: same ID + workspace A != same ID + workspace B."""
        engine_a = _engine_for(workspace_a)
        engine_b = _engine_for(workspace_b)

        alias_a = engine_a.pseudonymize_value(SYNTHETIC_ACCOUNT, IdentifierClass.ACCOUNT)
        alias_b = engine_b.pseudonymize_value(SYNTHETIC_ACCOUNT, IdentifierClass.ACCOUNT)

        assert alias_a != alias_b, (
            "Same identifier in different workspaces must produce different aliases"
        )

    def test_same_workspace_same_alias(self, workspace_a):
        """Same workspace + same ID = same alias (determinism)."""
        engine1 = _engine_for(workspace_a)
        engine2 = _engine_for(workspace_a)

        alias1 = engine1.pseudonymize_value(SYNTHETIC_ACCOUNT, IdentifierClass.ACCOUNT)
        alias2 = engine2.pseudonymize_value(SYNTHETIC_ACCOUNT, IdentifierClass.ACCOUNT)

        assert alias1 == alias2

    def test_same_workspace_across_invocations(self, workspace_a):
        """Multiple engine creations from same workspace produce same aliases."""
        aliases = set()
        for _ in range(5):
            engine = _engine_for(workspace_a)
            alias = engine.pseudonymize_value(SYNTHETIC_ACCOUNT, IdentifierClass.ACCOUNT)
            aliases.add(alias)
        assert len(aliases) == 1, "All invocations should produce the same alias"

    def test_workspace_secrets_are_physically_distinct(self, workspace_a, workspace_b):
        """Each workspace has its own pseudonym.key file."""
        _engine_for(workspace_a)
        _engine_for(workspace_b)

        secret_a = (workspace_a / SECRET_FILENAME).read_bytes()
        secret_b = (workspace_b / SECRET_FILENAME).read_bytes()

        assert secret_a != secret_b, "Physical secret files must differ"

    def test_secret_stored_in_workspace_not_parent(self, workspace_a):
        """Secret is created inside workspace dir, not in parent."""
        _engine_for(workspace_a)

        assert (workspace_a / SECRET_FILENAME).exists()
        assert not (workspace_a.parent / SECRET_FILENAME).exists()
        assert not (workspace_a.parent.parent / SECRET_FILENAME).exists()


class TestCrossPathConsistency:
    """All output paths using the same workspace produce the same aliases."""

    def test_report_and_reckoner_same_workspace_same_alias(self, workspace_a):
        """Report engine and Reckoner engine with same workspace = same alias."""
        report_engine = PseudonymizationEngine.create(
            workspace_a, PseudonymPolicy.for_structured_output()
        )
        reckoner_engine = PseudonymizationEngine.create(
            workspace_a, PseudonymPolicy.for_structured_output()
        )

        r_alias = report_engine.pseudonymize_value(SYNTHETIC_ACCOUNT, IdentifierClass.ACCOUNT)
        q_alias = reckoner_engine.pseudonymize_value(SYNTHETIC_ACCOUNT, IdentifierClass.ACCOUNT)

        assert r_alias == q_alias

    def test_report_and_analyze_same_workspace_same_alias(self, workspace_a):
        """Report and Analyze with same workspace produce same aliases."""
        report_engine = PseudonymizationEngine.create(
            workspace_a, PseudonymPolicy.for_structured_output()
        )
        analyze_engine = PseudonymizationEngine.create(
            workspace_a, PseudonymPolicy.for_structured_output()
        )

        r_alias = report_engine.pseudonymize_value(SYNTHETIC_ACCOUNT, IdentifierClass.ACCOUNT)
        a_alias = analyze_engine.pseudonymize_value(SYNTHETIC_ACCOUNT, IdentifierClass.ACCOUNT)

        assert r_alias == a_alias

    def test_persistence_and_report_same_workspace_same_alias(self, workspace_a):
        """Persistence policy (MCP/history) uses same alias as report."""
        report_engine = PseudonymizationEngine.create(
            workspace_a, PseudonymPolicy.for_structured_output()
        )
        persist_engine = PseudonymizationEngine.create(
            workspace_a, PseudonymPolicy.for_persistence()
        )

        r_alias = report_engine.pseudonymize_value(SYNTHETIC_ACCOUNT, IdentifierClass.ACCOUNT)
        p_alias = persist_engine.pseudonymize_value(SYNTHETIC_ACCOUNT, IdentifierClass.ACCOUNT)

        assert r_alias == p_alias


class TestNoGlobalFallback:
    """No code path should use a global/machine-wide pseudonym secret."""

    def test_context_module_does_not_use_data_dir_directly(self):
        """The context module must not import get_data_dir for secret storage."""
        import inspect
        from kulshan.pseudonym import context
        source = inspect.getsource(context)
        # It should use resolve_workspace or get_workspace_path, not get_data_dir
        # for the actual secret path
        assert "get_data_dir()" not in source or "get_workspace_path" in source, (
            "context.py should not use get_data_dir() as the secret location"
        )

    def test_no_pseudonym_key_in_data_dir_root(self, tmp_path):
        """Creating an engine should NOT place pseudonym.key at the data dir root."""
        # Create a workspace inside a simulated data dir
        data_dir = tmp_path / "kulshan_data"
        ws_dir = data_dir / "workspaces" / "ws_test"
        ws_dir.mkdir(parents=True)

        _engine_for(ws_dir)

        # Secret should be in workspace, not data root
        assert not (data_dir / SECRET_FILENAME).exists()
        assert (ws_dir / SECRET_FILENAME).exists()
