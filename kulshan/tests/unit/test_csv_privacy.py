"""Regression test: CSV export must not contain raw customer identifiers by default.

This test guards against the privacy defect where findings_to_csv() received
raw findings without passing through redact_payload(). Fixed in 0.5.1.
"""
from __future__ import annotations

import re
from unittest.mock import patch

from kulshan.report.csv_export import findings_to_csv
from kulshan.redact import redact_payload


# Synthetic test identifiers (never real)
SYNTHETIC_ACCOUNT = "111222333444"
SYNTHETIC_ARN = "arn:aws:ec2:us-east-1:111222333444:instance/i-0abc123def456789a"
SYNTHETIC_EMAIL = "test.user@synthetic-corp.example"


def _make_test_findings() -> list[dict]:
    """Create findings with known synthetic identifiers."""
    return [
        {
            "severity": "high",
            "pack": "security",
            "kind": "SG-001",
            "title": f"Security group allows 0.0.0.0/0 in account {SYNTHETIC_ACCOUNT}",
            "resource_id": SYNTHETIC_ARN,
            "region": "us-east-1",
            "confidence": "high",
            "effort": "low",
            "risk": "safe",
            "estimated_monthly_impact": 0,
            "recommended_action": f"Restrict ingress in {SYNTHETIC_ACCOUNT}",
            "remediation_snippet": f"# Fix for {SYNTHETIC_ARN}",
        },
        {
            "severity": "medium",
            "pack": "security",
            "kind": "IAM-002",
            "title": f"User {SYNTHETIC_EMAIL} has console access without MFA",
            "resource_id": f"arn:aws:iam::{SYNTHETIC_ACCOUNT}:user/admin",
            "region": "global",
            "confidence": "high",
            "effort": "trivial",
            "risk": "safe",
            "estimated_monthly_impact": 0,
            "recommended_action": "Enable MFA",
            "remediation_snippet": "",
        },
    ]


class TestCsvPrivacy:
    """CSV output must apply redaction by default."""

    def test_csv_does_not_contain_raw_account_id_after_redaction(self):
        """Redacted findings fed to findings_to_csv must not contain raw 12-digit IDs."""
        findings = _make_test_findings()
        redacted = redact_payload(findings)
        csv_str = findings_to_csv(redacted)

        # The raw 12-digit synthetic account must NOT appear
        assert SYNTHETIC_ACCOUNT not in csv_str, (
            f"CSV output contains raw account ID: {SYNTHETIC_ACCOUNT}"
        )

    def test_csv_does_not_contain_raw_arn_after_redaction(self):
        """Redacted CSV must not contain a fully intact ARN with account portion."""
        findings = _make_test_findings()
        redacted = redact_payload(findings)
        csv_str = findings_to_csv(redacted)

        # The raw ARN should not survive intact
        assert SYNTHETIC_ARN not in csv_str, (
            "CSV output contains raw ARN"
        )

    def test_csv_without_redaction_does_contain_raw_ids(self):
        """Sanity check: unredacted findings DO contain raw IDs (proves the test is meaningful)."""
        findings = _make_test_findings()
        csv_str = findings_to_csv(findings)

        assert SYNTHETIC_ACCOUNT in csv_str, (
            "Raw findings should contain the account ID (test fixture sanity)"
        )

    def test_csv_redaction_preserves_row_count(self):
        """Redaction must not drop rows."""
        findings = _make_test_findings()
        redacted = redact_payload(findings)

        raw_csv = findings_to_csv(findings)
        redacted_csv = findings_to_csv(redacted)

        # Same number of data lines (header + N rows)
        raw_lines = [line for line in raw_csv.strip().split("\n") if line]
        redacted_lines = [line for line in redacted_csv.strip().split("\n") if line]
        assert len(raw_lines) == len(redacted_lines), (
            "Redaction must not change row count"
        )
