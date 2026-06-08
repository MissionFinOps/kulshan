"""Unit tests for cost pack canonical Finding output.

Verifies that the cost pack's `_anomaly_to_finding()` and `aws_anomaly_to_finding()`
produce findings that pass orchestrator validation, populate all required fields
correctly, and conform to the canonical Finding schema (v2.0).

Requirements: 9.7, 3.3
"""
from __future__ import annotations

import re
from unittest.mock import patch

import pandas as pd
import pytest

from kulshan.checks.cost import _anomaly_to_finding, _build_findings, run_scan
from kulshan.checks.cost.aws_native import aws_anomaly_to_finding
from kulshan.models import VALID_EFFORT, VALID_RISK, VALID_SEVERITY
from kulshan.orchestrator import validate_finding


# ── Fixtures ──────────────────────────────────────────────────────────────────

_SAMPLE_ANOMALY = {
    "service": "Amazon Elastic Compute Cloud",
    "date": "2026-04-20",
    "severity": "critical",
    "latest_cost": 500.0,
    "avg_cost": 100.0,
    "pct_change": 400.0,
    "z_score": 4.2,
    "mad_score": 3.1,
    "methods": "zscore,iqr,mad",
    "num_methods": 3,
}

_SAMPLE_ATTRIBUTION = {
    "account": "000000000000",
    "account_share": 0.92,
    "region": "us-east-1",
    "region_share": 0.88,
    "usage_type": "USE1-BoxUsage:m5.xlarge",
    "usage_type_share": 0.75,
    "resource_id": "i-0123456789abcdef0",
    "notes": ["dominant account found"],
    "api_calls": 3,
}

_SAMPLE_AWS_ROW = {
    "anomaly_id": "Anomaly-Test-001",
    "start_date": "2026-04-18",
    "end_date": "2026-04-20",
    "service": "AWS Lambda",
    "region": "eu-west-1",
    "account": "111111111111",
    "usage_type": "EU-Lambda-GB-Second",
    "total_impact": 500.0,
    "max_impact": 400.0,
    "total_actual": 1000.0,
    "total_expected": 500.0,
    "feedback": "",
}


# ── _anomaly_to_finding: statistical anomaly conversion ───────────────────────


class TestAnomalyToFindingPassesValidation:
    """Statistical anomaly findings pass orchestrator validation."""

    def test_full_finding_passes_validation(self):
        finding = _anomaly_to_finding(_SAMPLE_ANOMALY, _SAMPLE_ATTRIBUTION)
        valid, reason = validate_finding(finding)
        assert valid, f"Validation failed: {reason}"

    def test_finding_without_attribution_passes_validation(self):
        finding = _anomaly_to_finding(_SAMPLE_ANOMALY, None)
        valid, reason = validate_finding(finding)
        assert valid, f"Validation failed: {reason}"

    def test_finding_with_empty_attribution_passes_validation(self):
        finding = _anomaly_to_finding(_SAMPLE_ANOMALY, {})
        valid, reason = validate_finding(finding)
        assert valid, f"Validation failed: {reason}"


class TestAnomalyToFindingFieldPopulation:
    """Verify correct field values on statistical findings."""

    def test_pack_is_cost(self):
        finding = _anomaly_to_finding(_SAMPLE_ANOMALY, _SAMPLE_ATTRIBUTION)
        assert finding["pack"] == "cost"

    def test_kind_is_anomaly_statistical(self):
        finding = _anomaly_to_finding(_SAMPLE_ANOMALY, _SAMPLE_ATTRIBUTION)
        assert finding["kind"] == "anomaly_statistical"

    def test_fingerprint_is_16_hex_chars(self):
        finding = _anomaly_to_finding(_SAMPLE_ANOMALY, _SAMPLE_ATTRIBUTION)
        assert re.fullmatch(r"[0-9a-f]{16}", finding["fingerprint"])

    def test_effort_has_valid_canonical_value(self):
        finding = _anomaly_to_finding(_SAMPLE_ANOMALY, _SAMPLE_ATTRIBUTION)
        assert finding["effort"] in VALID_EFFORT

    def test_risk_has_valid_canonical_value(self):
        finding = _anomaly_to_finding(_SAMPLE_ANOMALY, _SAMPLE_ATTRIBUTION)
        assert finding["risk"] in VALID_RISK

    def test_severity_has_valid_canonical_value(self):
        finding = _anomaly_to_finding(_SAMPLE_ANOMALY, _SAMPLE_ATTRIBUTION)
        assert finding["severity"] in VALID_SEVERITY

    def test_schema_version_is_2_0(self):
        finding = _anomaly_to_finding(_SAMPLE_ANOMALY, _SAMPLE_ATTRIBUTION)
        assert finding["schema_version"] == "2.0"

    def test_confidence_is_float_in_range(self):
        finding = _anomaly_to_finding(_SAMPLE_ANOMALY, _SAMPLE_ATTRIBUTION)
        assert isinstance(finding["confidence"], float)
        assert 0.0 <= finding["confidence"] <= 1.0

    def test_estimated_monthly_impact_is_non_negative_float(self):
        finding = _anomaly_to_finding(_SAMPLE_ANOMALY, _SAMPLE_ATTRIBUTION)
        assert isinstance(finding["estimated_monthly_impact"], float)
        assert finding["estimated_monthly_impact"] >= 0.0

    def test_account_id_populated_from_attribution(self):
        finding = _anomaly_to_finding(_SAMPLE_ANOMALY, _SAMPLE_ATTRIBUTION)
        assert finding["account_id"] == "000000000000"

    def test_service_populated_from_anomaly(self):
        finding = _anomaly_to_finding(_SAMPLE_ANOMALY, _SAMPLE_ATTRIBUTION)
        assert finding["service"] == "Amazon Elastic Compute Cloud"


# ── aws_anomaly_to_finding: AWS-native anomaly conversion ─────────────────────


class TestAwsNativePassesValidation:
    """AWS-native anomaly findings pass orchestrator validation."""

    def test_full_aws_finding_passes_validation(self):
        finding = aws_anomaly_to_finding(_SAMPLE_AWS_ROW)
        assert finding is not None
        valid, reason = validate_finding(finding)
        assert valid, f"Validation failed: {reason}"

    def test_aws_finding_with_minimal_fields_passes_validation(self):
        minimal = {
            "anomaly_id": "Min-001",
            "start_date": "2026-05-01",
            "end_date": "2026-05-01",
            "service": "Amazon S3",
            "region": "",
            "account": "",
            "usage_type": "",
            "total_impact": 10.0,
            "max_impact": 10.0,
            "total_actual": 20.0,
            "total_expected": 10.0,
            "feedback": "",
        }
        finding = aws_anomaly_to_finding(minimal)
        assert finding is not None
        valid, reason = validate_finding(finding)
        assert valid, f"Validation failed: {reason}"


class TestAwsNativeFieldPopulation:
    """Verify correct field values on AWS-native findings."""

    def test_pack_is_cost(self):
        finding = aws_anomaly_to_finding(_SAMPLE_AWS_ROW)
        assert finding["pack"] == "cost"

    def test_kind_is_anomaly_aws_native(self):
        finding = aws_anomaly_to_finding(_SAMPLE_AWS_ROW)
        assert finding["kind"] == "anomaly_aws_native"

    def test_fingerprint_is_16_hex_chars(self):
        finding = aws_anomaly_to_finding(_SAMPLE_AWS_ROW)
        assert re.fullmatch(r"[0-9a-f]{16}", finding["fingerprint"])

    def test_effort_has_valid_canonical_value(self):
        finding = aws_anomaly_to_finding(_SAMPLE_AWS_ROW)
        assert finding["effort"] in VALID_EFFORT

    def test_risk_has_valid_canonical_value(self):
        finding = aws_anomaly_to_finding(_SAMPLE_AWS_ROW)
        assert finding["risk"] in VALID_RISK

    def test_severity_has_valid_canonical_value(self):
        finding = aws_anomaly_to_finding(_SAMPLE_AWS_ROW)
        assert finding["severity"] in VALID_SEVERITY

    def test_schema_version_is_2_0(self):
        finding = aws_anomaly_to_finding(_SAMPLE_AWS_ROW)
        assert finding["schema_version"] == "2.0"

    def test_confidence_is_float_in_range(self):
        finding = aws_anomaly_to_finding(_SAMPLE_AWS_ROW)
        assert isinstance(finding["confidence"], float)
        assert 0.0 <= finding["confidence"] <= 1.0


# ── Empty findings case ───────────────────────────────────────────────────────


class TestEmptyFindings:
    """When no anomalies exist, the findings list is empty `[]`."""

    def test_build_findings_with_empty_dataframe(self):
        errors: list = []
        result = _build_findings(
            fetcher=None,
            anomalies_df=pd.DataFrame(),
            max_attributions=5,
            days=30,
            errors=errors,
        )
        assert result == []

    def test_build_findings_with_none_dataframe(self):
        errors: list = []
        result = _build_findings(
            fetcher=None,
            anomalies_df=None,
            max_attributions=5,
            days=30,
            errors=errors,
        )
        assert result == []

    def test_run_scan_empty_cost_data_returns_empty_findings(self):
        """When CostFetcher returns empty data, findings list is empty."""

        class _EmptyFetcher:
            def get_cost_by_dimension(self, dim, days=30, **kwargs):
                return pd.DataFrame()

            def get_anomalies_from_service(self, days):
                return pd.DataFrame()

            def get_reservation_coverage(self, days=30):
                return pd.DataFrame()

            def get_savings_plans_utilization(self, days=30):
                return pd.DataFrame()

            def get_reservation_utilization(self, days=30):
                return pd.DataFrame()

        with patch(
            "kulshan.checks.cost.cost_fetcher.CostFetcher",
            return_value=_EmptyFetcher(),
        ):
            result = run_scan(profile=None, days=30)

        # Empty data means no cost data → _empty() path with empty findings
        assert isinstance(result["findings"], list)
        assert result["findings"] == []


# ── total_findings matches len(findings) ──────────────────────────────────────


class TestTotalFindingsMatchesLength:
    """The scores.total_findings value equals len(findings)."""

    def test_with_findings(self):
        """When findings are produced, total_findings == len(findings)."""

        class _FindingFetcher:
            def get_cost_by_dimension(self, dim, days=30, **kwargs):
                # Enough data so detect_anomalies might find something
                dates = pd.date_range(end="2026-04-20", periods=30)
                rows = [
                    {"date": d, "service": "EC2", "cost": 100.0} for d in dates
                ]
                return pd.DataFrame(rows)

            def get_cost_by_service_and_account(self, days, service_filter=None):
                return pd.DataFrame()

            def get_top_resources(self, days=14):
                return pd.DataFrame()

            def get_anomalies_from_service(self, days):
                return pd.DataFrame()

            def get_reservation_coverage(self, days=30):
                return pd.DataFrame()

            def get_savings_plans_utilization(self, days=30):
                return pd.DataFrame()

            def get_reservation_utilization(self, days=30):
                return pd.DataFrame()

        with patch(
            "kulshan.checks.cost.cost_fetcher.CostFetcher",
            return_value=_FindingFetcher(),
        ):
            result = run_scan(profile=None, days=30)

        assert result["scores"]["total_findings"] == len(result["findings"])

    def test_with_no_findings(self):
        """Even with _empty() path, total_findings == 0 == len([])."""

        class _EmptyFetcher:
            def get_cost_by_dimension(self, dim, days=30, **kwargs):
                return pd.DataFrame()

            def get_anomalies_from_service(self, days):
                return pd.DataFrame()

            def get_reservation_coverage(self, days=30):
                return pd.DataFrame()

            def get_savings_plans_utilization(self, days=30):
                return pd.DataFrame()

            def get_reservation_utilization(self, days=30):
                return pd.DataFrame()

        with patch(
            "kulshan.checks.cost.cost_fetcher.CostFetcher",
            return_value=_EmptyFetcher(),
        ):
            result = run_scan(profile=None, days=30)

        assert result["scores"]["total_findings"] == len(result["findings"])
        assert result["scores"]["total_findings"] == 0


# ── All findings from run_scan pass validation ────────────────────────────────


class TestRunScanAllFindingsPassValidation:
    """Every finding from run_scan passes orchestrator validate_finding()."""

    def test_all_findings_validate(self):
        """When run_scan produces findings, each one passes validation."""

        class _AnomalyFetcher:
            def get_cost_by_dimension(self, dim, days=30, **kwargs):
                # Create a service with a big spike to trigger anomaly detection
                dates = pd.date_range(end="2026-04-20", periods=30)
                rows = []
                for i, d in enumerate(dates):
                    cost = 100.0 if i < 29 else 900.0  # spike on last day
                    rows.append({"date": d, "service": "EC2 - Other", "cost": cost})
                return pd.DataFrame(rows)

            def get_cost_by_service_and_account(self, days, service_filter=None):
                return pd.DataFrame()

            def get_top_resources(self, days=14):
                return pd.DataFrame()

            def get_anomalies_from_service(self, days):
                # Also include an AWS-native anomaly
                return pd.DataFrame([{
                    "anomaly_id": "A-001",
                    "start_date": "2026-04-19",
                    "end_date": "2026-04-20",
                    "service": "AWS Lambda",
                    "region": "us-east-1",
                    "account": "000000000000",
                    "usage_type": "USE1-Lambda-GB-Second",
                    "total_impact": 200.0,
                    "max_impact": 200.0,
                    "total_actual": 400.0,
                    "total_expected": 200.0,
                    "feedback": "",
                }])

            def get_reservation_coverage(self, days=30):
                return pd.DataFrame()

            def get_savings_plans_utilization(self, days=30):
                return pd.DataFrame()

            def get_reservation_utilization(self, days=30):
                return pd.DataFrame()

        with patch(
            "kulshan.checks.cost.cost_fetcher.CostFetcher",
            return_value=_AnomalyFetcher(),
        ):
            result = run_scan(profile=None, days=30)

        findings = result["findings"]
        # We expect at least the AWS-native finding
        assert len(findings) >= 1

        for idx, f in enumerate(findings):
            valid, reason = validate_finding(f)
            assert valid, f"Finding {idx} failed validation: {reason}"
            # Also verify canonical field constraints
            assert f["pack"] == "cost"
            assert f["kind"] in ("anomaly_statistical", "anomaly_aws_native")
            assert re.fullmatch(r"[0-9a-f]{16}", f["fingerprint"])
            assert f["effort"] in VALID_EFFORT
            assert f["risk"] in VALID_RISK
            assert f["schema_version"] == "2.0"
