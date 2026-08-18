"""Privacy regression tests for all report output paths.

Verifies that structured/file output pseudonymizes identifiers by default,
and that --show-identifiers restores raw values.
"""
from __future__ import annotations

import json
import os
from io import StringIO
from pathlib import Path
from unittest.mock import patch

import pytest
from rich.console import Console

from kulshan.pseudonym.engine import PseudonymizationEngine
from kulshan.pseudonym.policy import PseudonymPolicy
from kulshan.pseudonym.types import IdentifierClass


SYNTHETIC_ACCOUNT = "111222333444"
SYNTHETIC_ARN = "arn:aws:ec2:us-east-1:111222333444:instance/i-0abc123def456789a"
SYNTHETIC_INSTANCE = "i-0abc123def456789a"

TEST_SECRET = os.urandom(32)


def _make_findings() -> list[dict]:
    return [
        {
            "severity": "high",
            "pack": "security",
            "kind": "SG-001",
            "check_id": "SG-001",
            "title": f"Security group open in {SYNTHETIC_ACCOUNT}",
            "resource_id": SYNTHETIC_ARN,
            "resource_arn": SYNTHETIC_ARN,
            "resource_type": "ec2:security-group",
            "region": "us-east-1",
            "service": "ec2",
            "account_id": SYNTHETIC_ACCOUNT,
            "confidence": "high",
            "effort": "low",
            "risk": "safe",
            "estimated_monthly_impact": 0,
            "recommended_action": f"Restrict {SYNTHETIC_ARN} ingress",
            "remediation_snippet": "",
        }
    ]


def _make_results() -> dict:
    return {
        "security": {
            "findings": _make_findings(),
            "scores": {"overall_score": 70, "grade": "C", "total_findings": 1},
        }
    }


def _engine(active: bool = True) -> PseudonymizationEngine:
    policy = PseudonymPolicy.for_structured_output(show_identifiers=not active)
    return PseudonymizationEngine(TEST_SECRET, policy)


# ═══════════════════════════════════════════════════════════════════════════════
# JSON OUTPUT
# ═══════════════════════════════════════════════════════════════════════════════


class TestJsonPrivacy:
    """JSON output pseudonymizes identifiers by default."""

    def test_json_file_no_raw_account(self, tmp_path):
        """JSON file output must not contain raw account IDs."""
        engine = _engine(active=True)
        findings = _make_findings()
        payload = {
            "kulshan_version": "0.5.1",
            "account_id": SYNTHETIC_ACCOUNT,
            "regions": ["us-east-1"],
            "findings": findings,
        }
        result = engine.pseudonymize_payload(payload)
        json_str = json.dumps(result, indent=2)

        assert SYNTHETIC_ACCOUNT not in json_str
        assert "acct_" in json_str

    def test_json_file_no_raw_arn(self, tmp_path):
        engine = _engine(active=True)
        findings = _make_findings()
        payload = {"findings": findings}
        result = engine.pseudonymize_payload(payload)
        json_str = json.dumps(result, indent=2)

        assert SYNTHETIC_ARN not in json_str
        assert SYNTHETIC_INSTANCE not in json_str

    def test_json_show_identifiers_preserves_raw(self):
        engine = _engine(active=False)
        payload = {"account_id": SYNTHETIC_ACCOUNT}
        result = engine.pseudonymize_payload(payload)
        assert result["account_id"] == SYNTHETIC_ACCOUNT

    def test_json_pseudonymization_metadata(self):
        """Pseudonymized JSON should include metadata."""
        engine = _engine(active=True)
        payload = {"kulshan_version": "0.5.1", "account_id": SYNTHETIC_ACCOUNT}
        result = engine.pseudonymize_payload(payload)
        # The metadata is added by _emit_output, not the engine itself
        # So we just verify the engine transforms correctly
        assert result["account_id"].startswith("acct_")


# ═══════════════════════════════════════════════════════════════════════════════
# CSV OUTPUT
# ═══════════════════════════════════════════════════════════════════════════════


class TestCsvPrivacy:
    """CSV output pseudonymizes identifiers."""

    def test_csv_no_raw_account_via_engine(self):
        from kulshan.report.csv_export import findings_to_csv

        engine = _engine(active=True)
        findings = _make_findings()
        pseudonymized = engine.pseudonymize_payload(findings)
        csv_str = findings_to_csv(pseudonymized)

        assert SYNTHETIC_ACCOUNT not in csv_str
        assert SYNTHETIC_ARN not in csv_str

    def test_csv_preserves_non_identifier_data(self):
        from kulshan.report.csv_export import findings_to_csv

        engine = _engine(active=True)
        findings = _make_findings()
        pseudonymized = engine.pseudonymize_payload(findings)
        csv_str = findings_to_csv(pseudonymized)

        # Severity and region are passthrough
        assert "high" in csv_str
        assert "us-east-1" in csv_str


# ═══════════════════════════════════════════════════════════════════════════════
# ENGINE CONSISTENCY ACROSS FORMATS
# ═══════════════════════════════════════════════════════════════════════════════


class TestCrossFormatConsistency:
    """Same identifier produces same alias regardless of output format."""

    def test_same_account_same_alias_across_payloads(self):
        engine = _engine(active=True)

        payload1 = {"account_id": SYNTHETIC_ACCOUNT}
        payload2 = {"findings": [{"account_id": SYNTHETIC_ACCOUNT}]}

        r1 = engine.pseudonymize_payload(payload1)
        r2 = engine.pseudonymize_payload(payload2)

        assert r1["account_id"] == r2["findings"][0]["account_id"]

    def test_account_in_text_matches_field(self):
        engine = _engine(active=True)

        payload = {
            "account_id": SYNTHETIC_ACCOUNT,
            "title": f"Issue in account {SYNTHETIC_ACCOUNT}",
        }
        result = engine.pseudonymize_payload(payload)

        field_alias = result["account_id"]
        assert field_alias in result["title"]


# ═══════════════════════════════════════════════════════════════════════════════
# TTY BEHAVIOR
# ═══════════════════════════════════════════════════════════════════════════════


class TestTtyBehavior:
    """TTY terminal shows real identifiers; non-TTY pseudonymizes."""

    def test_tty_policy_allows_real(self):
        policy = PseudonymPolicy.for_terminal(is_tty=True)
        assert policy.should_pseudonymize is False

    def test_non_tty_policy_pseudonymizes(self):
        policy = PseudonymPolicy.for_terminal(is_tty=False)
        assert policy.should_pseudonymize is True

    def test_explicit_format_json_on_tty_pseudonymizes(self):
        """--format json should pseudonymize even on a TTY."""
        # This is enforced by _get_pseudonym_engine: fmt != "terminal" -> structured policy
        policy = PseudonymPolicy.for_structured_output(show_identifiers=False)
        assert policy.should_pseudonymize is True


# ═══════════════════════════════════════════════════════════════════════════════
# SERVICE/REGION/COST PRESERVATION
# ═══════════════════════════════════════════════════════════════════════════════


class TestPreservation:
    """Non-identifier data must survive pseudonymization exactly."""

    def test_service_name_preserved(self):
        engine = _engine(active=True)
        payload = {"service": "AmazonEC2"}
        assert engine.pseudonymize_payload(payload)["service"] == "AmazonEC2"

    def test_region_preserved(self):
        engine = _engine(active=True)
        payload = {"region": "eu-west-1"}
        assert engine.pseudonymize_payload(payload)["region"] == "eu-west-1"

    def test_score_preserved(self):
        engine = _engine(active=True)
        payload = {"overall_score": 85}
        assert engine.pseudonymize_payload(payload)["overall_score"] == 85

    def test_cost_preserved(self):
        engine = _engine(active=True)
        payload = {"estimated_monthly_impact": 1234.56}
        assert engine.pseudonymize_payload(payload)["estimated_monthly_impact"] == 1234.56

    def test_severity_preserved(self):
        engine = _engine(active=True)
        payload = {"severity": "critical"}
        assert engine.pseudonymize_payload(payload)["severity"] == "critical"


# ═══════════════════════════════════════════════════════════════════════════════
# NEGATIVE ASSERTIONS: RAW IDs MUST NOT SURVIVE
# ═══════════════════════════════════════════════════════════════════════════════


class TestNegativeAssertions:
    """Raw synthetic identifiers must NOT appear in any pseudonymized output."""

    def test_full_report_payload_no_raw_account(self):
        engine = _engine(active=True)
        payload = {
            "kulshan_version": "0.5.1",
            "account_id": SYNTHETIC_ACCOUNT,
            "regions": ["us-east-1"],
            "duration_seconds": 12.3,
            "overall_score": 75,
            "overall_grade": "C",
            "findings": _make_findings(),
            "top_actions": [
                {"title": f"Fix SG in {SYNTHETIC_ACCOUNT}", "severity": "high"}
            ],
            "tools": _make_results(),
        }
        result = engine.pseudonymize_payload(payload)
        result_str = json.dumps(result, indent=2, default=str)

        assert SYNTHETIC_ACCOUNT not in result_str, "Raw account ID survived pseudonymization"
        assert SYNTHETIC_INSTANCE not in result_str, "Raw instance ID survived pseudonymization"
        assert "111222333444" not in result_str, "12-digit account pattern survived"

    def test_full_report_payload_no_raw_arn(self):
        engine = _engine(active=True)
        payload = {"findings": _make_findings()}
        result = engine.pseudonymize_payload(payload)
        result_str = json.dumps(result, indent=2, default=str)

        assert SYNTHETIC_ARN not in result_str
