"""Tests for orchestrator adapter integration (task 9.1).

Validates that:
- Legacy-shaped findings (tool/check_id without pack/kind) are adapted before validation
- Packs that don't emit findings get empty "findings": [] in their results
- Canonical findings pass through without adaptation
"""
from __future__ import annotations

import io
import logging
from unittest.mock import MagicMock, patch

import pytest
from rich.console import Console

from kulshan.orchestrator import _is_legacy_finding, run_all_scans, validate_finding


def _quiet_console():
    """Return a Console that discards output (suitable for tests)."""
    return Console(file=io.StringIO(), quiet=True)


# ---------------------------------------------------------------------------
# Tests for _is_legacy_finding helper
# ---------------------------------------------------------------------------


class TestIsLegacyFinding:
    """Tests for the _is_legacy_finding detection helper."""

    def test_tool_without_pack_is_legacy(self):
        finding = {"tool": "security", "check_id": "iam_root_mfa", "title": "Root MFA"}
        assert _is_legacy_finding(finding) is True

    def test_check_id_without_kind_is_legacy(self):
        finding = {"pack": "security", "check_id": "iam_root_mfa", "title": "Root MFA"}
        assert _is_legacy_finding(finding) is True

    def test_missing_both_pack_and_kind_is_legacy(self):
        finding = {"title": "Something", "severity": "high"}
        assert _is_legacy_finding(finding) is True

    def test_canonical_finding_not_legacy(self):
        finding = {
            "id": "cost-test-abc",
            "pack": "cost",
            "kind": "anomaly_statistical",
            "title": "Test",
            "severity": "high",
            "confidence": 0.85,
            "effort": "medium",
            "risk": "safe",
        }
        assert _is_legacy_finding(finding) is False

    def test_finding_with_both_pack_and_kind_not_legacy(self):
        finding = {"pack": "security", "kind": "iam", "title": "Test"}
        assert _is_legacy_finding(finding) is False

    def test_non_dict_not_legacy(self):
        assert _is_legacy_finding("not a dict") is False
        assert _is_legacy_finding(None) is False
        assert _is_legacy_finding(42) is False

    def test_tool_with_pack_not_legacy(self):
        """If both tool and pack are present, pack takes priority → not legacy."""
        finding = {"tool": "security", "pack": "security", "kind": "iam", "title": "Test"}
        assert _is_legacy_finding(finding) is False


# ---------------------------------------------------------------------------
# Tests for adapter integration in run_all_scans
# ---------------------------------------------------------------------------


class TestAdapterIntegration:
    """Tests for adapter being called on legacy findings in run_all_scans."""

    @patch("kulshan.orchestrator._load_check")
    def test_legacy_findings_adapted_and_validated(self, mock_load):
        """Legacy-shaped findings are adapted to canonical form before validation."""
        mock_check = MagicMock()
        # Legacy finding: has 'tool' and 'check_id' but no 'pack'/'kind'
        mock_check.run_scan.return_value = {
            "scores": {"overall_score": 80, "grade": "B", "total_findings": 1, "severity_counts": {}},
            "findings": [
                {
                    "tool": "security",
                    "check_id": "iam_root_mfa",
                    "title": "Root account MFA not enabled",
                    "severity": "critical",
                    "confidence": "high",  # enum string → should be adapted to float
                    "monthly_impact_usd": "0.0",
                }
            ],
            "errors": [],
        }
        mock_load.return_value = mock_check

        results = run_all_scans(
            session=MagicMock(),
            regions=["us-east-1"],
            console=_quiet_console(),
        )

        # The first tool is "cost" — the legacy finding should be adapted & pass validation
        cost_findings = results["cost"]["findings"]
        assert len(cost_findings) == 1
        f = cost_findings[0]
        # Adapter should have mapped tool→pack, check_id→kind
        assert f["pack"] == "security"  # from the 'tool' field in raw finding
        assert f["kind"] == "iam_root_mfa"  # from check_id
        # Confidence should be adapted from enum string to float
        assert isinstance(f["confidence"], float)
        assert f["confidence"] == 0.85  # "high" → 0.85
        # Should have canonical keys
        assert "effort" in f
        assert "risk" in f
        assert "id" in f
        assert "fingerprint" in f

    @patch("kulshan.orchestrator._load_check")
    def test_canonical_findings_pass_through_without_adaptation(self, mock_load):
        """Canonical findings are not modified by the adapter."""
        canonical_finding = {
            "id": "cost-anomaly-abc123",
            "pack": "cost",
            "kind": "anomaly_statistical",
            "title": "EC2 cost spike",
            "severity": "high",
            "confidence": 0.85,
            "effort": "medium",
            "risk": "safe",
            "score_impact": -10,
            "estimated_monthly_impact": 4500.0,
            "fingerprint": "a1b2c3d4e5f6g7h8",
        }
        mock_check = MagicMock()
        mock_check.run_scan.return_value = {
            "scores": {"overall_score": 80, "grade": "B", "total_findings": 1, "severity_counts": {}},
            "findings": [canonical_finding],
            "errors": [],
        }
        mock_load.return_value = mock_check

        results = run_all_scans(
            session=MagicMock(),
            regions=["us-east-1"],
            console=_quiet_console(),
        )

        # All packs get the same mock, so check cost
        cost_findings = results["cost"]["findings"]
        assert len(cost_findings) == 1
        f = cost_findings[0]
        # Should be unchanged (not adapted)
        assert f["id"] == "cost-anomaly-abc123"
        assert f["pack"] == "cost"
        assert f["kind"] == "anomaly_statistical"
        assert f["confidence"] == 0.85

    @patch("kulshan.orchestrator._load_check")
    def test_packs_without_findings_key_get_empty_list(self, mock_load):
        """Packs that don't include 'findings' in their result get an empty list."""
        mock_check = MagicMock()
        mock_check.run_scan.return_value = {
            "scores": {"overall_score": 90, "grade": "A", "total_findings": 0, "severity_counts": {}},
            "errors": [],
            # No "findings" key at all
        }
        mock_load.return_value = mock_check

        results = run_all_scans(
            session=MagicMock(),
            regions=["us-east-1"],
            console=_quiet_console(),
        )

        # All 10 packs should have a "findings" key with an empty list
        for tool_key in results:
            assert "findings" in results[tool_key]
            assert results[tool_key]["findings"] == []

    @patch("kulshan.orchestrator._load_check")
    def test_non_migrated_packs_skipped_get_empty_findings(self, mock_load):
        """Non-migrated packs that are skipped (not installed) get empty findings."""
        # Return None for all checks (simulating not installed)
        mock_load.return_value = None

        results = run_all_scans(
            session=MagicMock(),
            regions=["us-east-1"],
            console=_quiet_console(),
        )

        # All 10 packs should be present with empty findings
        assert len(results) == 10
        for tool_key in results:
            assert "findings" in results[tool_key]
            assert results[tool_key]["findings"] == []

    @patch("kulshan.orchestrator._load_check")
    def test_mixed_legacy_and_canonical_findings(self, mock_load):
        """Mix of legacy and canonical findings: legacy gets adapted, canonical passes through."""
        mock_check = MagicMock()
        mock_check.run_scan.return_value = {
            "scores": {"overall_score": 70, "grade": "C", "total_findings": 2, "severity_counts": {}},
            "findings": [
                # Canonical finding
                {
                    "id": "cost-anomaly-x1",
                    "pack": "cost",
                    "kind": "anomaly_statistical",
                    "title": "Canonical finding",
                    "severity": "medium",
                    "confidence": 0.6,
                    "effort": "low",
                    "risk": "safe",
                },
                # Legacy finding (tool without pack)
                {
                    "tool": "cost",
                    "check_id": "waste_ebs",
                    "title": "Unused EBS volume",
                    "severity": "low",
                    "confidence": "medium",
                    "monthly_impact_usd": "25.50",
                },
            ],
            "errors": [],
        }
        mock_load.return_value = mock_check

        results = run_all_scans(
            session=MagicMock(),
            regions=["us-east-1"],
            console=_quiet_console(),
        )

        cost_findings = results["cost"]["findings"]
        assert len(cost_findings) == 2
        # First is canonical, untouched
        assert cost_findings[0]["id"] == "cost-anomaly-x1"
        assert cost_findings[0]["confidence"] == 0.6
        # Second is adapted from legacy
        assert cost_findings[1]["pack"] == "cost"
        assert cost_findings[1]["kind"] == "waste_ebs"
        assert isinstance(cost_findings[1]["confidence"], float)
        assert cost_findings[1]["confidence"] == 0.6  # "medium" → 0.6
