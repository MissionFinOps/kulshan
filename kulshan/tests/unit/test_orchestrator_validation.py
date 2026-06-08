"""Tests for orchestrator finding validation integration (task 3.2).

Validates that run_all_scans() filters invalid findings, logs warnings,
and handles missing 'findings' keys gracefully.
"""
from __future__ import annotations

import io
import logging
from unittest.mock import MagicMock, patch

import pytest
from rich.console import Console

from kulshan.orchestrator import run_all_scans, validate_finding


def _quiet_console():
    """Return a Console that discards output (suitable for tests)."""
    return Console(file=io.StringIO(), quiet=True)


def _valid_finding(**overrides):
    """Return a minimal valid finding dict."""
    base = {
        "id": "cost-test-abc123",
        "pack": "cost",
        "kind": "anomaly_statistical",
        "title": "Test finding",
        "severity": "high",
        "confidence": 0.85,
        "effort": "medium",
        "risk": "safe",
    }
    base.update(overrides)
    return base


def _invalid_finding(**overrides):
    """Return a finding dict that will fail validation."""
    base = _valid_finding()
    base["severity"] = "INVALID_SEVERITY"
    base.update(overrides)
    return base


class TestValidationIntegration:
    """Tests for validate_finding integration in run_all_scans."""

    @patch("kulshan.orchestrator._load_check")
    def test_valid_findings_kept(self, mock_load):
        """Valid findings remain in results after validation."""
        mock_check = MagicMock()
        mock_check.run_scan.return_value = {
            "scores": {"overall_score": 80, "grade": "B", "total_findings": 2, "severity_counts": {}},
            "findings": [_valid_finding(id="f1"), _valid_finding(id="f2")],
            "errors": [],
        }
        mock_load.return_value = mock_check

        results = run_all_scans(
            session=MagicMock(),
            regions=["us-east-1"],
            console=_quiet_console(),
        )

        # All valid findings should be kept
        for tool_key in results:
            if not results[tool_key].get("skipped"):
                assert len(results[tool_key]["findings"]) == 2

    @patch("kulshan.orchestrator._load_check")
    def test_invalid_findings_excluded(self, mock_load):
        """Invalid findings are removed from results."""
        mock_check = MagicMock()
        mock_check.run_scan.return_value = {
            "scores": {"overall_score": 80, "grade": "B", "total_findings": 3, "severity_counts": {}},
            "findings": [
                _valid_finding(id="f1"),
                _invalid_finding(id="f2"),
                _valid_finding(id="f3"),
            ],
            "errors": [],
        }
        mock_load.return_value = mock_check

        results = run_all_scans(
            session=MagicMock(),
            regions=["us-east-1"],
            console=_quiet_console(),
        )

        # Only valid findings should remain
        for tool_key in results:
            if not results[tool_key].get("skipped"):
                assert len(results[tool_key]["findings"]) == 2
                ids = [f["id"] for f in results[tool_key]["findings"]]
                assert "f1" in ids
                assert "f3" in ids
                assert "f2" not in ids

    @patch("kulshan.orchestrator._load_check")
    def test_invalid_findings_logged(self, mock_load, caplog):
        """Invalid findings produce a warning log with pack name, index, and reason."""
        mock_check = MagicMock()
        mock_check.run_scan.return_value = {
            "scores": {"overall_score": 80, "grade": "B", "total_findings": 1, "severity_counts": {}},
            "findings": [_invalid_finding()],
            "errors": [],
        }
        mock_load.return_value = mock_check

        with caplog.at_level(logging.WARNING, logger="kulshan.orchestrator"):
            results = run_all_scans(
                session=MagicMock(),
                regions=["us-east-1"],
                console=_quiet_console(),
            )

        # Should have logged a warning for each tool that had the invalid finding
        warning_messages = [r.message for r in caplog.records if r.levelno == logging.WARNING]
        assert len(warning_messages) > 0
        # The log should contain the pack name and finding index
        assert any("cost" in msg and "0" in msg for msg in warning_messages)

    @patch("kulshan.orchestrator._load_check")
    def test_missing_findings_key_treated_as_empty(self, mock_load):
        """If a pack result has no 'findings' key, treat as empty list (no error)."""
        mock_check = MagicMock()
        # Return dict without 'findings' key
        mock_check.run_scan.return_value = {
            "scores": {"overall_score": 90, "grade": "A", "total_findings": 0, "severity_counts": {}},
            "errors": [],
        }
        mock_load.return_value = mock_check

        # Should not crash
        results = run_all_scans(
            session=MagicMock(),
            regions=["us-east-1"],
            console=_quiet_console(),
        )

        # All packs should have findings key set to empty list
        for tool_key in results:
            assert results[tool_key]["findings"] == []

    @patch("kulshan.orchestrator._load_check")
    def test_non_dict_finding_excluded(self, mock_load):
        """A non-dict finding is excluded via validation failure."""
        mock_check = MagicMock()
        mock_check.run_scan.return_value = {
            "scores": {"overall_score": 80, "grade": "B", "total_findings": 2, "severity_counts": {}},
            "findings": [_valid_finding(id="f1"), "not a dict", None, 42],
            "errors": [],
        }
        mock_load.return_value = mock_check

        results = run_all_scans(
            session=MagicMock(),
            regions=["us-east-1"],
            console=_quiet_console(),
        )

        # Only the valid dict finding should remain
        for tool_key in results:
            if not results[tool_key].get("skipped"):
                assert len(results[tool_key]["findings"]) == 1
                assert results[tool_key]["findings"][0]["id"] == "f1"

    @patch("kulshan.orchestrator._load_check")
    def test_scan_does_not_crash_on_invalid_finding(self, mock_load):
        """Invalid findings do not crash the scan — graceful degradation."""
        mock_check = MagicMock()
        mock_check.run_scan.return_value = {
            "scores": {"overall_score": 50, "grade": "D", "total_findings": 1, "severity_counts": {}},
            "findings": [_invalid_finding()],
            "errors": [],
        }
        mock_load.return_value = mock_check

        # Should not raise any exception
        results = run_all_scans(
            session=MagicMock(),
            regions=["us-east-1"],
            console=_quiet_console(),
        )

        # Results should still be populated for all tools
        assert len(results) == 10
