"""Tests for workspace pseudonymization secret lifecycle."""
from __future__ import annotations

import os
import stat
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

from kulshan.pseudonym.secret import (
    SECRET_FILENAME,
    SECRET_LENGTH,
    SecretCorruptError,
    SecretCreationError,
    load_or_create_secret,
)


@pytest.fixture
def workspace_dir(tmp_path: Path) -> Path:
    """Create a temporary workspace directory."""
    ws = tmp_path / "ws_test"
    ws.mkdir()
    return ws


class TestSecretCreation:
    """Secret is created atomically with correct properties."""

    def test_creates_secret_file(self, workspace_dir: Path):
        secret = load_or_create_secret(workspace_dir)
        assert len(secret) == SECRET_LENGTH
        assert (workspace_dir / SECRET_FILENAME).exists()

    def test_secret_is_random(self, workspace_dir: Path):
        secret = load_or_create_secret(workspace_dir)
        # A 32-byte random value should not be all zeros
        assert secret != b"\x00" * SECRET_LENGTH

    def test_secret_file_is_32_bytes(self, workspace_dir: Path):
        load_or_create_secret(workspace_dir)
        data = (workspace_dir / SECRET_FILENAME).read_bytes()
        assert len(data) == SECRET_LENGTH

    @pytest.mark.skipif(sys.platform == "win32", reason="POSIX permissions not enforced on Windows")
    def test_secret_file_permissions_posix(self, workspace_dir: Path):
        load_or_create_secret(workspace_dir)
        secret_path = workspace_dir / SECRET_FILENAME
        mode = stat.S_IMODE(secret_path.stat().st_mode)
        assert mode == 0o600, f"Expected 0o600, got {oct(mode)}"

    def test_creates_parent_directories(self, tmp_path: Path):
        deep_path = tmp_path / "a" / "b" / "c"
        secret = load_or_create_secret(deep_path)
        assert len(secret) == SECRET_LENGTH
        assert (deep_path / SECRET_FILENAME).exists()


class TestSecretLoading:
    """Existing secret is loaded consistently."""

    def test_returns_same_value_on_reload(self, workspace_dir: Path):
        first = load_or_create_secret(workspace_dir)
        second = load_or_create_secret(workspace_dir)
        assert first == second

    def test_deterministic_across_calls(self, workspace_dir: Path):
        """Multiple loads always return the same bytes."""
        results = [load_or_create_secret(workspace_dir) for _ in range(10)]
        assert all(r == results[0] for r in results)


class TestSecretCorruption:
    """Corrupt secrets fail closed."""

    def test_short_file_raises_corrupt(self, workspace_dir: Path):
        secret_path = workspace_dir / SECRET_FILENAME
        secret_path.write_bytes(b"too short")
        with pytest.raises(SecretCorruptError) as exc_info:
            load_or_create_secret(workspace_dir)
        assert str(workspace_dir) in str(exc_info.value)

    def test_long_file_raises_corrupt(self, workspace_dir: Path):
        secret_path = workspace_dir / SECRET_FILENAME
        secret_path.write_bytes(os.urandom(64))  # Too long
        with pytest.raises(SecretCorruptError):
            load_or_create_secret(workspace_dir)

    def test_empty_file_raises_corrupt(self, workspace_dir: Path):
        secret_path = workspace_dir / SECRET_FILENAME
        secret_path.write_bytes(b"")
        with pytest.raises(SecretCorruptError):
            load_or_create_secret(workspace_dir)

    def test_corrupt_error_message_includes_path(self, workspace_dir: Path):
        secret_path = workspace_dir / SECRET_FILENAME
        secret_path.write_bytes(b"x")
        with pytest.raises(SecretCorruptError) as exc_info:
            load_or_create_secret(workspace_dir)
        assert "delete the file" in str(exc_info.value)


class TestSecretRaceCondition:
    """Concurrent creation is handled safely."""

    def test_race_condition_reads_winner(self, workspace_dir: Path):
        """If file is created between exists() check and open(), we read it."""
        winner_secret = os.urandom(SECRET_LENGTH)

        # Write the "winner's" file before our atomic create runs
        secret_path = workspace_dir / SECRET_FILENAME
        secret_path.write_bytes(winner_secret)

        result = load_or_create_secret(workspace_dir)
        assert result == winner_secret


class TestSecretIsolation:
    """Different workspaces have different secrets."""

    def test_different_workspaces_different_secrets(self, tmp_path: Path):
        ws1 = tmp_path / "ws_1"
        ws2 = tmp_path / "ws_2"
        ws1.mkdir()
        ws2.mkdir()

        s1 = load_or_create_secret(ws1)
        s2 = load_or_create_secret(ws2)

        assert s1 != s2, "Different workspaces must have different secrets"
