"""Unit tests for AWS-native Cost Anomaly Detection ingestion and overlap classification.

Phase 6B. Covers:

- ``aws_anomaly_to_finding`` row → Finding mapping (severity, monthly impact, fingerprint)
- Empty / error / suppression paths
- ``severity_from_impact`` thresholds
- ``matches_overlap`` rules (service / account / date window)
- ``classify_findings`` bucketing
- ``apply_overlap_boost`` mutates confidence + records ``overlap_with``
- Fixture parity (no real account IDs)
- ``cost.run_scan`` integration with metadata block
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from unittest.mock import patch

import pandas as pd
import pytest

from kulshan.checks.cost import _build_aws_native_findings, run_scan
from kulshan.checks.cost.aws_native import (
    DEFAULT_AWS_CONFIDENCE,
    OVERLAP_BOOSTED_CONFIDENCE,
    OVERLAP_DATE_TOLERANCE_DAYS,
    SEVERITY_THRESHOLDS,
    apply_overlap_boost,
    aws_anomaly_to_finding,
    classify_findings,
    matches_overlap,
    severity_from_impact,
)


FIXTURE_PATH = (
    Path(__file__).resolve().parents[1]
    / "fixtures"
    / "cost"
    / "aws_native_anomaly_cases.json"
)


def _load_rows() -> dict:
    return json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))["rows"]


# ── severity_from_impact ──────────────────────────────────────────────────────


class TestSeverityFromImpact:
    @pytest.mark.parametrize(
        "impact,expected",
        [
            (10000.0, "critical"),
            (5000.0, "critical"),
            (2500.0, "high"),
            (1000.0, "high"),
            (500.0, "medium"),
            (100.0, "medium"),
            (50.0, "low"),
            (10.0, "low"),
            (1.0, "info"),
            (0.0, "info"),
        ],
    )
    def test_thresholds(self, impact, expected):
        assert severity_from_impact(impact) == expected

    def test_feedback_yes_bumps_to_critical(self):
        # Even tiny impact: human said it was real.
        assert severity_from_impact(1.0, feedback="YES") == "critical"

    def test_feedback_yes_case_insensitive(self):
        assert severity_from_impact(1.0, feedback="yes") == "critical"

    def test_feedback_no_does_not_bump(self):
        # NO suppresses entirely at the conversion layer; severity stays normal here.
        assert severity_from_impact(50.0, feedback="NO") == "low"

    def test_invalid_impact_treated_as_zero(self):
        assert severity_from_impact("not-a-number") == "info"
        assert severity_from_impact(None) == "info"

    def test_thresholds_constant_shape(self):
        # Locked structure (impact_threshold, severity).
        assert SEVERITY_THRESHOLDS == (
            (5000.0, "critical"),
            (1000.0, "high"),
            (100.0, "medium"),
            (10.0, "low"),
        )


# ── aws_anomaly_to_finding ────────────────────────────────────────────────────


class TestAwsAnomalyToFinding:
    def test_full_row_populates_all_fields(self):
        row = _load_rows()["nat_gateway_critical_overlap"]
        f = aws_anomaly_to_finding(row)
        assert f is not None
        assert f["pack"] == "cost"
        assert f["kind"] == "anomaly_aws_native"
        assert f["account_id"] == "000000000000"
        assert f["region"] == "us-east-1"
        assert f["service"] == "EC2 - Other"
        assert f["evidence"]["usage_type"] == "USE1-NatGateway-Bytes"
        assert f["confidence"] == DEFAULT_AWS_CONFIDENCE
        assert f["evidence"]["source"] == "aws_cost_anomaly_detection"
        assert f["evidence"]["aws_anomaly_id"] == "AnomalyOverlap-0001"
        assert f["evidence"]["anomaly_days"] == 2
        assert "AnomalyOverlap-0001" in f["recommended_action"]
        # Title contains key context
        assert "EC2 - Other" in f["title"]
        assert "us-east-1" in f["title"]
        assert "000000000000" in f["title"]
        # Severity comes from $1247 → "high"
        assert f["severity"] == "high"
        assert f["score_impact"] == -10  # high → -10 per Phase 6 Q4

    def test_feedback_no_returns_none(self):
        row = _load_rows()["user_marked_no"]
        assert aws_anomaly_to_finding(row) is None

    def test_feedback_yes_makes_critical(self):
        row = _load_rows()["user_confirmed_yes"]
        f = aws_anomaly_to_finding(row)
        assert f is not None
        assert f["severity"] == "critical"
        assert f["score_impact"] == -15

    def test_low_severity_for_small_impact(self):
        row = _load_rows()["rds_low_severity"]
        f = aws_anomaly_to_finding(row)
        assert f is not None
        assert f["severity"] == "low"
        assert f["score_impact"] == -2

    def test_monthly_impact_proxy_for_multi_day_window(self):
        # nat_gateway_critical_overlap: 2-day window, $1247 → daily $623.75 × 30 = $18712.50
        row = _load_rows()["nat_gateway_critical_overlap"]
        f = aws_anomaly_to_finding(row)
        # 1247.50 / 2 * 30 = 18712.50
        assert f["estimated_monthly_impact"] == 18712.50

    def test_monthly_impact_proxy_for_single_day(self):
        # rds_low_severity: same start/end (1-day-effective). 45.20 / 1 * 30 = 1356.00
        row = _load_rows()["rds_low_severity"]
        f = aws_anomaly_to_finding(row)
        assert f["estimated_monthly_impact"] == 1356.00

    def test_missing_dates_falls_back_to_total_impact(self):
        row = {
            "anomaly_id": "X",
            "start_date": "",
            "end_date": "",
            "service": "AWS Lambda",
            "region": "",
            "account": "000000000000",
            "usage_type": "",
            "total_impact": 250.0,
            "max_impact": 250.0,
            "total_actual": 500.0,
            "total_expected": 250.0,
            "feedback": "",
        }
        f = aws_anomaly_to_finding(row)
        assert f["estimated_monthly_impact"] == 250.0

    def test_empty_root_cause_fields_handled(self):
        row = _load_rows()["no_root_cause"]
        f = aws_anomaly_to_finding(row)
        assert f is not None
        assert f["account_id"] is None
        assert f["region"] is None
        assert f["evidence"]["usage_type"] is None
        assert f["service"] == "Unknown"  # AWS returns literal "Unknown"

    def test_fingerprint_is_stable_across_calls(self):
        row = _load_rows()["nat_gateway_critical_overlap"]
        a = aws_anomaly_to_finding(row)
        b = aws_anomaly_to_finding(row)
        assert a["fingerprint"] == b["fingerprint"]
        assert a["id"] == b["id"]

    def test_fingerprint_differs_from_statistical_for_same_period(self):
        """Kulshan statistical and AWS-native findings for the same anomaly
        produce different fingerprints because ``kind`` differs. The bridge
        between them is overlap classification, not fingerprint equality."""
        from kulshan.models import compute_fingerprint
        from datetime import date

        stat_fp = compute_fingerprint(
            pack="cost", kind="anomaly_statistical",
            account="000000000000", service="EC2 - Other",
            usage_type="USE1-NatGateway-Bytes",
            period=date(2026, 4, 14),
        )
        row = _load_rows()["nat_gateway_critical_overlap"]
        aws_f = aws_anomaly_to_finding(row)
        assert aws_f["fingerprint"] != stat_fp

    def test_finding_is_json_serializable(self):
        row = _load_rows()["nat_gateway_critical_overlap"]
        f = aws_anomaly_to_finding(row)
        json.dumps(f)  # must not raise


# ── _build_aws_native_findings (run_scan integration) ─────────────────────────


class _FakeFetcher:
    """Stub for ``fetcher.get_anomalies_from_service``."""

    def __init__(self, *, df=None, raise_exc=None):
        self._df = df
        self._raise = raise_exc
        self.calls = 0

    def get_anomalies_from_service(self, days):
        self.calls += 1
        if self._raise:
            raise self._raise
        return self._df if self._df is not None else pd.DataFrame()


class TestBuildAwsNativeFindings:
    def test_empty_dataframe_returns_no_data_status(self):
        errors: list = []
        findings, meta = _build_aws_native_findings(
            _FakeFetcher(df=pd.DataFrame()), lookback_days=90, errors=errors,
        )
        assert findings == []
        assert meta["status"] == "no_data"
        assert meta["lookback_days"] == 90
        assert meta["anomaly_count"] == 0
        assert errors == []

    def test_none_dataframe_returns_no_data(self):
        errors: list = []
        findings, meta = _build_aws_native_findings(
            _FakeFetcher(df=None), lookback_days=30, errors=errors,
        )
        assert findings == []
        assert meta["status"] == "no_data"

    def test_fetcher_exception_returns_error_status(self):
        errors: list = []
        findings, meta = _build_aws_native_findings(
            _FakeFetcher(raise_exc=RuntimeError("simulated")),
            lookback_days=30, errors=errors,
        )
        assert findings == []
        assert meta["status"] == "error"
        assert "simulated" in meta["details"]
        assert any("simulated" in e for e in errors)

    def test_normal_path_builds_findings(self):
        rows = _load_rows()
        df = pd.DataFrame([
            rows["nat_gateway_critical_overlap"],
            rows["lambda_aws_only"],
        ])
        errors: list = []
        findings, meta = _build_aws_native_findings(
            _FakeFetcher(df=df), lookback_days=90, errors=errors,
        )
        assert len(findings) == 2
        assert meta["status"] == "ok"
        assert meta["anomaly_count"] == 2

    def test_feedback_no_rows_are_suppressed(self):
        rows = _load_rows()
        df = pd.DataFrame([
            rows["nat_gateway_critical_overlap"],
            rows["user_marked_no"],
        ])
        errors: list = []
        findings, meta = _build_aws_native_findings(
            _FakeFetcher(df=df), lookback_days=90, errors=errors,
        )
        assert len(findings) == 1
        assert meta["status"] == "ok"
        assert meta["anomaly_count"] == 1
        assert "1 of 2 anomalies suppressed" in meta["details"]

    def test_all_suppressed_returns_no_data_with_details(self):
        rows = _load_rows()
        df = pd.DataFrame([rows["user_marked_no"]])
        errors: list = []
        findings, meta = _build_aws_native_findings(
            _FakeFetcher(df=df), lookback_days=90, errors=errors,
        )
        assert findings == []
        assert meta["status"] == "no_data"
        assert "all 1" in meta["details"]


# ── matches_overlap ───────────────────────────────────────────────────────────


def _stat_finding(**overrides) -> dict:
    base = {
        "id": "cost-anomaly_statistical-aaaaaaaaaaaaaaaa",
        "pack": "cost",
        "kind": "anomaly_statistical",
        "service": "EC2 - Other",
        "account": "000000000000",
        "evidence": {"date": "2026-04-14"},
    }
    base.update(overrides)
    return base


def _aws_finding(**overrides) -> dict:
    base = {
        "id": "cost-anomaly_aws_native-bbbbbbbbbbbbbbbb",
        "pack": "cost",
        "kind": "anomaly_aws_native",
        "service": "EC2 - Other",
        "account": "000000000000",
        "evidence": {"start_date": "2026-04-13", "end_date": "2026-04-15"},
    }
    base.update(overrides)
    return base


class TestMatchesOverlap:
    def test_same_service_same_account_date_in_window_matches(self):
        assert matches_overlap(_stat_finding(), _aws_finding()) is True

    def test_different_service_no_match(self):
        assert (
            matches_overlap(
                _stat_finding(service="AWS Lambda"),
                _aws_finding(service="EC2 - Other"),
            )
            is False
        )

    def test_different_account_when_both_populated_no_match(self):
        assert (
            matches_overlap(
                _stat_finding(account="000000000000"),
                _aws_finding(account="111111111111"),
            )
            is False
        )

    def test_one_side_missing_account_lenient_match(self):
        assert (
            matches_overlap(
                _stat_finding(account=None),
                _aws_finding(account="111111111111"),
            )
            is True
        )

    def test_date_inside_tolerance_matches(self):
        # Kulshan date = 2026-04-12 (1 day before AWS window starts 2026-04-13)
        # Tolerance is 2 days → still in window.
        assert (
            matches_overlap(
                _stat_finding(evidence={"date": "2026-04-12"}),
                _aws_finding(),
            )
            is True
        )

    def test_date_outside_tolerance_no_match(self):
        # 2026-04-10 is 3 days before window start 2026-04-13, outside tolerance.
        assert (
            matches_overlap(
                _stat_finding(evidence={"date": "2026-04-10"}),
                _aws_finding(),
            )
            is False
        )

    def test_unparseable_date_no_match(self):
        assert (
            matches_overlap(
                _stat_finding(evidence={"date": "not-a-date"}),
                _aws_finding(),
            )
            is False
        )

    def test_missing_service_no_match(self):
        assert (
            matches_overlap(_stat_finding(service=None), _aws_finding()) is False
        )

    def test_overlap_tolerance_constant(self):
        assert OVERLAP_DATE_TOLERANCE_DAYS == 2


# ── classify_findings ─────────────────────────────────────────────────────────


class TestClassifyFindings:
    def test_pure_Kulshan_only(self):
        result = classify_findings([_stat_finding()], [])
        assert result["both"] == []
        assert result["aws_only"] == []
        assert len(result["Kulshan_only"]) == 1

    def test_pure_aws_only(self):
        result = classify_findings([], [_aws_finding()])
        assert result["both"] == []
        assert result["Kulshan_only"] == []
        assert len(result["aws_only"]) == 1

    def test_both_when_overlap(self):
        result = classify_findings([_stat_finding()], [_aws_finding()])
        assert len(result["both"]) == 1
        assert result["both"][0] == (
            "cost-anomaly_statistical-aaaaaaaaaaaaaaaa",
            "cost-anomaly_aws_native-bbbbbbbbbbbbbbbb",
        )
        assert result["Kulshan_only"] == []
        assert result["aws_only"] == []

    def test_one_Kulshan_pairs_with_multiple_aws(self):
        reck = [_stat_finding()]
        aws = [
            _aws_finding(id="aws-1"),
            _aws_finding(id="aws-2"),
        ]
        result = classify_findings(reck, aws)
        assert len(result["both"]) == 2
        assert result["Kulshan_only"] == []
        assert result["aws_only"] == []

    def test_mixed_buckets(self):
        reck = [
            _stat_finding(id="reck-match", service="EC2 - Other"),
            _stat_finding(id="reck-alone", service="Amazon S3"),
        ]
        aws = [
            _aws_finding(id="aws-match", service="EC2 - Other"),
            _aws_finding(id="aws-alone", service="AWS Lambda"),
        ]
        result = classify_findings(reck, aws)
        assert len(result["both"]) == 1
        assert result["Kulshan_only"] == ["reck-alone"]
        assert result["aws_only"] == ["aws-alone"]


# ── apply_overlap_boost ───────────────────────────────────────────────────────


class TestApplyOverlapBoost:
    def test_matched_Kulshan_finding_gets_confidence_boost(self):
        reck = [_stat_finding(confidence=0.65)]
        aws = [_aws_finding(confidence=DEFAULT_AWS_CONFIDENCE)]
        apply_overlap_boost(reck, aws)
        assert reck[0]["confidence"] == OVERLAP_BOOSTED_CONFIDENCE
        assert aws[0]["confidence"] == OVERLAP_BOOSTED_CONFIDENCE

    def test_unmatched_finding_keeps_original_confidence(self):
        reck = [_stat_finding(confidence=0.65, service="Amazon S3")]
        aws = [_aws_finding(confidence=DEFAULT_AWS_CONFIDENCE, service="EC2 - Other")]
        apply_overlap_boost(reck, aws)
        assert reck[0]["confidence"] == 0.65
        assert aws[0]["confidence"] == DEFAULT_AWS_CONFIDENCE

    def test_evidence_overlap_with_recorded_on_both_sides(self):
        reck = [_stat_finding(id="reck-A")]
        aws = [_aws_finding(id="aws-X")]
        apply_overlap_boost(reck, aws)
        assert reck[0]["evidence"]["overlap_with"] == ["aws-X"]
        assert aws[0]["evidence"]["overlap_with"] == ["reck-A"]

    def test_returns_classification_dict(self):
        result = apply_overlap_boost([_stat_finding()], [_aws_finding()])
        assert "both" in result
        assert "Kulshan_only" in result
        assert "aws_only" in result


# ── run_scan integration ──────────────────────────────────────────────────────


class _IntegrationFetcher:
    """Minimal fetcher driving the cost.run_scan path far enough to exercise the
    Phase 6B code path. Returns just enough for the run_scan to construct
    findings; everything else degrades to empty / zero."""

    def __init__(self, *, aws_df=None, aws_raise=None):
        self._aws_df = aws_df
        self._aws_raise = aws_raise

    def get_cost_by_dimension(self, dim, days=30, **kwargs):
        # Synthetic 30-day series; enough for detect_anomalies but no anomaly.
        if dim == "service":
            import pandas as pd
            dates = pd.date_range(end=pd.Timestamp.utcnow().normalize(), periods=10)
            return pd.DataFrame([
                {"date": d, "service": "EC2 - Other", "cost": 100.0}
                for d in dates
            ])
        return pd.DataFrame()

    def get_cost_by_service_and_account(self, days, service_filter=None):
        return pd.DataFrame()

    def get_top_resources(self, days=14):
        return pd.DataFrame()

    def get_reservation_coverage(self, days=30):
        return pd.DataFrame()

    def get_savings_plans_utilization(self, days=30):
        return pd.DataFrame()

    def get_reservation_utilization(self, days=30):
        return pd.DataFrame()

    def get_anomalies_from_service(self, days):
        if self._aws_raise:
            raise self._aws_raise
        return self._aws_df if self._aws_df is not None else pd.DataFrame()


class TestRunScanIntegration:
    def test_metadata_block_is_added(self):
        fetcher = _IntegrationFetcher(aws_df=pd.DataFrame())
        with patch(
            "kulshan.checks.cost.cost_fetcher.CostFetcher",
            return_value=fetcher,
        ):
            result = run_scan(profile=None, days=30)
        assert "metadata" in result
        assert "cost_anomaly_detection" in result["metadata"]
        meta = result["metadata"]["cost_anomaly_detection"]
        assert meta["status"] == "no_data"
        assert meta["lookback_days"] == 30
        assert meta["anomaly_count"] == 0
        assert "overlap" in meta
        assert meta["overlap"]["both_count"] == 0

    def test_metadata_records_aws_anomaly_count(self):
        rows = _load_rows()
        df = pd.DataFrame([rows["lambda_aws_only"]])
        fetcher = _IntegrationFetcher(aws_df=df)
        with patch(
            "kulshan.checks.cost.cost_fetcher.CostFetcher",
            return_value=fetcher,
        ):
            result = run_scan(profile=None, days=90)
        assert result["metadata"]["cost_anomaly_detection"]["status"] == "ok"
        assert result["metadata"]["cost_anomaly_detection"]["anomaly_count"] == 1
        # And the finding should be in the findings list with kind=anomaly_aws_native.
        kinds = {f["kind"] for f in result["findings"]}
        assert "anomaly_aws_native" in kinds

    def test_existing_scores_shape_unchanged(self):
        fetcher = _IntegrationFetcher(aws_df=pd.DataFrame())
        with patch(
            "kulshan.checks.cost.cost_fetcher.CostFetcher",
            return_value=fetcher,
        ):
            result = run_scan(profile=None, days=30)
        scores = result["scores"]
        # Lock the keys (Phase 6 spec, scores shape must remain unchanged).
        expected_keys = {
            "overall_score",
            "grade",
            "total_findings",
            "severity_counts",
            "breakdown",
            "total_spend",
        }
        assert set(scores.keys()) == expected_keys

    def test_aws_lookback_capped_at_90_days(self):
        """When user passes days > 90, AWS lookback caps at 90."""
        fetcher = _IntegrationFetcher(aws_df=pd.DataFrame())
        with patch(
            "kulshan.checks.cost.cost_fetcher.CostFetcher",
            return_value=fetcher,
        ):
            result = run_scan(profile=None, days=365)
        assert result["metadata"]["cost_anomaly_detection"]["lookback_days"] == 90

    def test_aws_fetcher_failure_does_not_break_scan(self):
        fetcher = _IntegrationFetcher(aws_raise=RuntimeError("simulated AWS error"))
        with patch(
            "kulshan.checks.cost.cost_fetcher.CostFetcher",
            return_value=fetcher,
        ):
            result = run_scan(profile=None, days=30)
        # Scan still completes; metadata records the error.
        assert result["metadata"]["cost_anomaly_detection"]["status"] == "error"
        assert any("simulated AWS error" in e for e in result["errors"])
        # findings list still exists (just empty for AWS side).
        assert isinstance(result["findings"], list)


# ── fixture safety ────────────────────────────────────────────────────────────


def test_no_real_account_ids_in_aws_fixture():
    text = FIXTURE_PATH.read_text(encoding="utf-8")
    allowed = {"000000000000", "111111111111", "222222222222"}
    found = re.findall(r"\b\d{12}\b", text)
    assert found, "fixture should contain placeholder account IDs"
    leaked = [f for f in found if f not in allowed]
    assert not leaked, f"fixture has non-placeholder 12-digit IDs: {leaked}"
