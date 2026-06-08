"""Unit tests for cost-pack anomaly attribution and finding construction.

Phase 6A. Covers the drill-down algorithm, edge cases, fixture-driven cases, and
the conversion of an analyzer anomaly row into a normalized Finding dict.
"""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from kulshan.checks.cost import _anomaly_to_finding, _build_findings
from kulshan.checks.cost.attribution import (
    DOMINANCE_THRESHOLD,
    attribute_anomaly,
    build_attribution_title,
    find_dominant,
    recommend_action,
)


FIXTURE_PATH = (
    Path(__file__).resolve().parents[1]
    / "fixtures"
    / "cost"
    / "anomaly_attribution_cases.json"
)


# ── fake fetcher ──────────────────────────────────────────────────────────────


class _FakeFetcher:
    """Minimal CostFetcher stand-in. Returns canned DataFrames for the 4 methods used."""

    def __init__(
        self,
        *,
        account_data=None,
        region_data=None,
        usage_data=None,
        resource_data=None,
        raise_on=(),
    ):
        self._acct = account_data
        self._region = region_data
        self._usage = usage_data
        self._res = resource_data
        self._raise_on = set(raise_on)
        self.calls: list[str] = []

    def get_cost_by_service_and_account(self, days, service_filter=None):
        self.calls.append("acct")
        if "acct" in self._raise_on:
            raise RuntimeError("simulated CE error: account")
        return self._acct if self._acct is not None else pd.DataFrame()

    def get_cost_by_dimension(
        self, dim, days=30, granularity="DAILY", service_filter=None, **kwargs
    ):
        self.calls.append(dim)
        if dim in self._raise_on:
            raise RuntimeError(f"simulated CE error: {dim}")
        if dim == "region":
            return self._region if self._region is not None else pd.DataFrame()
        if dim == "usage_type":
            return self._usage if self._usage is not None else pd.DataFrame()
        return pd.DataFrame()

    def get_top_resources(self, days=14):
        self.calls.append("resources")
        if "resources" in self._raise_on:
            raise RuntimeError("simulated CE error: resources")
        return self._res if self._res is not None else pd.DataFrame()


def _df(rows):
    return pd.DataFrame(rows) if rows else pd.DataFrame()


# ── find_dominant ─────────────────────────────────────────────────────────────


class TestFindDominant:
    def test_returns_dominant_when_share_above_threshold(self):
        df = _df([
            {"account": "000000000000", "cost": 800.0},
            {"account": "111111111111", "cost": 100.0},
            {"account": "222222222222", "cost": 100.0},
        ])
        result = find_dominant(df, "account")
        assert result is not None
        key, share = result
        assert key == "000000000000"
        assert 0.79 < share < 0.81

    def test_returns_none_when_no_dominant(self):
        df = _df([
            {"account": "000000000000", "cost": 250.0},
            {"account": "111111111111", "cost": 250.0},
            {"account": "222222222222", "cost": 250.0},
            {"account": "000000000000", "cost": 250.0},  # equally distributed
        ])
        # group sums: 500 / 250 / 250 → 50% share → below threshold
        assert find_dominant(df, "account") is None

    def test_handles_empty(self):
        assert find_dominant(pd.DataFrame(), "account") is None

    def test_handles_none(self):
        assert find_dominant(None, "account") is None

    def test_handles_zero_total(self):
        df = _df([{"account": "X", "cost": 0.0}])
        assert find_dominant(df, "account") is None

    def test_handles_missing_columns(self):
        df = _df([{"foo": "bar", "baz": 1.0}])
        assert find_dominant(df, "account") is None

    def test_threshold_is_60_percent(self):
        # exactly 60% must satisfy >= threshold
        assert DOMINANCE_THRESHOLD == 0.60


# ── attribute_anomaly ─────────────────────────────────────────────────────────


class TestAttributeAnomaly:
    def test_drills_to_dominant_account_region_and_usage(self):
        fetcher = _FakeFetcher(
            account_data=_df([
                {"account": "000000000000", "cost": 800.0},
                {"account": "111111111111", "cost": 100.0},
                {"account": "222222222222", "cost": 100.0},
            ]),
            region_data=_df([
                {"region": "us-east-1", "cost": 950.0},
                {"region": "us-west-2", "cost": 50.0},
            ]),
            usage_data=_df([
                {"usage_type": "USE1-NatGateway-Bytes", "cost": 880.0},
                {"usage_type": "USE1-DataTransfer-Out-Bytes", "cost": 120.0},
            ]),
        )
        result = attribute_anomaly(
            fetcher, {"service": "EC2 - Other", "date": "2026-04-15"}
        )
        assert result["account"] == "000000000000"
        assert result["region"] == "us-east-1"
        assert result["usage_type"] == "USE1-NatGateway-Bytes"
        assert result["resource_id"] is None  # not a Compute service
        assert result["api_calls"] == 3

    def test_no_clear_account_recorded_in_notes(self):
        fetcher = _FakeFetcher(
            account_data=_df([
                {"account": "000000000000", "cost": 100.0},
                {"account": "111111111111", "cost": 100.0},
                {"account": "222222222222", "cost": 100.0},
            ]),
            region_data=_df([{"region": "eu-west-1", "cost": 100.0}]),
        )
        result = attribute_anomaly(
            fetcher, {"service": "AWS Lambda", "date": "2026-04-16"}
        )
        assert result["account"] is None
        assert any("dominant account" in n for n in result["notes"])

    def test_handles_account_fetch_error_gracefully(self):
        fetcher = _FakeFetcher(raise_on=("acct",))
        result = attribute_anomaly(
            fetcher, {"service": "EC2", "date": "2026-04-15"}
        )
        assert result["account"] is None
        assert any("account fetch failed" in n for n in result["notes"])
        assert result["api_calls"] == 0  # fetch counted only on success

    def test_handles_region_fetch_error_keeps_going(self):
        fetcher = _FakeFetcher(
            account_data=_df([{"account": "000000000000", "cost": 1000}]),
            usage_data=_df([{"usage_type": "X", "cost": 1000}]),
            raise_on=("region",),
        )
        result = attribute_anomaly(
            fetcher, {"service": "EC2", "date": "2026-04-15"}
        )
        # account succeeds; region fails (logged); usage_type succeeds.
        assert result["account"] == "000000000000"
        assert result["region"] is None
        assert result["usage_type"] == "X"
        assert any("region fetch failed" in n for n in result["notes"])

    def test_resource_id_not_attempted_for_non_compute_service(self):
        fetcher = _FakeFetcher(
            resource_data=_df([
                {"resource_id": "i-abc", "cost": 700.0},
                {"resource_id": "i-def", "cost": 100.0},
            ]),
        )
        attribute_anomaly(fetcher, {"service": "Amazon S3", "date": "2026-04-15"})
        assert "resources" not in fetcher.calls

    def test_resource_id_attached_when_compute_service(self):
        fetcher = _FakeFetcher(
            account_data=_df([{"account": "000000000000", "cost": 1000}]),
            resource_data=_df([
                {"resource_id": "i-0aaaa1234567890ab", "cost": 900.0},
                {"resource_id": "i-0bbbb1234567890cd", "cost": 100.0},
            ]),
        )
        result = attribute_anomaly(
            fetcher,
            {
                "service": "Amazon Elastic Compute Cloud - Compute",
                "date": "2026-04-17",
            },
        )
        assert result["resource_id"] == "i-0aaaa1234567890ab"

    def test_resource_id_not_attached_when_no_dominant_resource(self):
        fetcher = _FakeFetcher(
            account_data=_df([{"account": "000000000000", "cost": 1000}]),
            resource_data=_df([
                {"resource_id": "i-1", "cost": 500.0},
                {"resource_id": "i-2", "cost": 500.0},
            ]),
        )
        result = attribute_anomaly(
            fetcher,
            {
                "service": "Amazon Elastic Compute Cloud - Compute",
                "date": "2026-04-17",
            },
        )
        assert result["resource_id"] is None

    def test_missing_service_short_circuits(self):
        fetcher = _FakeFetcher()
        result = attribute_anomaly(fetcher, {"date": "2026-04-15"})
        assert result["account"] is None
        assert result["api_calls"] == 0
        assert any("missing service" in n for n in result["notes"])

    def test_empty_account_data_handled(self):
        fetcher = _FakeFetcher(account_data=pd.DataFrame())
        result = attribute_anomaly(
            fetcher, {"service": "EC2", "date": "2026-04-15"}
        )
        assert result["account"] is None
        assert any("no service+account data" in n for n in result["notes"])


# ── titles & recommendations ──────────────────────────────────────────────────


class TestBuildAttributionTitle:
    def test_full_attribution(self):
        title = build_attribution_title(
            {"service": "EC2 - Other", "pct_change": 98.0},
            {
                "account": "000000000000", "account_share": 0.78,
                "region": "us-east-1", "region_share": 0.95,
                "usage_type": "USE1-NatGateway-Bytes", "usage_type_share": 0.88,
            },
        )
        assert "EC2 - Other spike" in title
        assert "78% in account 000000000000" in title
        assert "95% in us-east-1" in title
        assert "88% USE1-NatGateway-Bytes" in title

    def test_no_clear_driver(self):
        title = build_attribution_title(
            {"service": "AWS Lambda", "pct_change": 42.0},
            {"account": None, "region": None, "usage_type": None},
        )
        assert "AWS Lambda" in title
        assert "no clear single driver" in title

    def test_drop_uses_drop_word(self):
        title = build_attribution_title(
            {"service": "Amazon S3", "pct_change": -50.0},
            {"account": None, "region": None, "usage_type": None},
        )
        assert "drop" in title

    def test_partial_attribution(self):
        title = build_attribution_title(
            {"service": "Amazon RDS", "pct_change": 30.0},
            {
                "account": None, "region": "us-east-1", "region_share": 0.90,
                "usage_type": None,
            },
        )
        assert "Amazon RDS" in title
        assert "us-east-1" in title


class TestRecommendAction:
    def test_no_account(self):
        rec = recommend_action({"service": "EC2"}, {"account": None})
        assert "no single account" in rec.lower()

    def test_full_attribution(self):
        rec = recommend_action(
            {"service": "EC2 - Other"},
            {
                "account": "000000000000",
                "region": "us-east-1",
                "usage_type": "USE1-NatGateway-Bytes",
                "resource_id": "i-0aaaa1234567890ab",
            },
        )
        assert "000000000000" in rec
        assert "us-east-1" in rec
        assert "USE1-NatGateway-Bytes" in rec
        assert "i-0aaaa1234567890ab" in rec


# ── _anomaly_to_finding ───────────────────────────────────────────────────────


class TestAnomalyToFinding:
    def _row(self, **overrides):
        base = {
            "service": "EC2 - Other",
            "date": "2026-04-15",
            "latest_cost": 896.33,
            "avg_cost": 452.10,
            "pct_change": 98.3,
            "z_score": 4.1,
            "mad_score": 5.2,
            "methods": "Z:4.1σ, IQR, MAD:5.2",
            "num_methods": 3,
            "severity": "critical",
        }
        base.update(overrides)
        return base

    def test_full_attribution_populates_all_fields(self):
        finding = _anomaly_to_finding(
            self._row(),
            {
                "account": "000000000000", "account_share": 0.78,
                "region": "us-east-1", "region_share": 0.95,
                "usage_type": "USE1-NatGateway-Bytes", "usage_type_share": 0.88,
                "resource_id": None,
                "notes": [], "api_calls": 3,
            },
        )
        assert finding["pack"] == "cost"
        assert finding["kind"] == "anomaly_statistical"
        assert finding["severity"] == "critical"
        assert finding["score_impact"] == -15
        assert finding["account_id"] == "000000000000"
        assert finding["region"] == "us-east-1"
        assert finding["service"] == "EC2 - Other"
        assert finding["evidence"]["usage_type"] == "USE1-NatGateway-Bytes"
        assert finding["evidence"]["z_score"] == 4.1
        assert finding["evidence"]["num_methods"] == 3
        assert finding["evidence"]["attribution_api_calls"] == 3
        assert "78%" in finding["title"]
        assert "Investigate in account 000000000000" in finding["recommended_action"]
        assert finding["risk"] == "safe"
        assert finding["effort"] == "medium"
        assert 0.0 <= finding["confidence"] <= 1.0

    def test_estimated_monthly_impact_uses_daily_delta_x_30(self):
        finding = _anomaly_to_finding(
            self._row(latest_cost=200.0, avg_cost=100.0),
            None,
        )
        # daily delta = 100 → monthly proxy ≈ 3000
        assert finding["estimated_monthly_impact"] == 3000.0

    def test_severity_mapping_warning_to_high(self):
        finding = _anomaly_to_finding(self._row(severity="warning"), None)
        assert finding["severity"] == "high"
        assert finding["score_impact"] == -10

    def test_severity_mapping_info_to_low(self):
        finding = _anomaly_to_finding(self._row(severity="info"), None)
        assert finding["severity"] == "low"
        assert finding["score_impact"] == -2

    def test_unknown_severity_falls_back_to_low(self):
        finding = _anomaly_to_finding(self._row(severity="???"), None)
        assert finding["severity"] == "low"

    def test_no_attribution_yields_no_clear_driver_title(self):
        finding = _anomaly_to_finding(self._row(), None)
        assert "no clear single driver" in finding["title"]
        assert finding["account_id"] is None

    def test_finding_is_json_serializable(self):
        finding = _anomaly_to_finding(self._row(), None)
        json.dumps(finding)  # must not raise

    def test_fingerprint_is_stable_across_calls(self):
        a = _anomaly_to_finding(self._row(), None)
        b = _anomaly_to_finding(self._row(), None)
        assert a["fingerprint"] == b["fingerprint"]
        assert a["id"] == b["id"]


# ── _build_findings ───────────────────────────────────────────────────────────


class TestBuildFindings:
    def _anom_df(self, n: int) -> pd.DataFrame:
        return pd.DataFrame([
            {
                "service": f"Service-{i}",
                "date": "2026-04-15",
                "latest_cost": 200.0 + i,
                "avg_cost": 100.0,
                "pct_change": 100.0,
                "z_score": 3.0,
                "mad_score": 3.0,
                "methods": "Z:3",
                "num_methods": 1,
                "severity": "warning",
                "score": 3.0,
            }
            for i in range(n)
        ])

    def test_top_n_anomalies_get_attribution_rest_do_not(self):
        # 7 anomalies, max_attributions=3 → only first 3 hit the fetcher.
        fetcher = _FakeFetcher(
            account_data=_df([{"account": "000000000000", "cost": 1000}]),
        )
        errors: list = []
        findings = _build_findings(
            fetcher, self._anom_df(7),
            max_attributions=3, days=14, errors=errors,
        )
        assert len(findings) == 7
        # First three made 3 CE calls each (acct+region+usage_type) = 9.
        # Remaining 4 made 0.
        # _FakeFetcher returns empty for region/usage_type by default → 3 calls each.
        assert fetcher.calls.count("acct") == 3

    def test_returns_empty_when_no_anomalies(self):
        errors: list = []
        findings = _build_findings(
            _FakeFetcher(), pd.DataFrame(),
            max_attributions=5, days=14, errors=errors,
        )
        assert findings == []
        assert errors == []

    def test_attribution_failure_recorded_but_does_not_break(self):
        fetcher = _FakeFetcher(raise_on=("acct",))
        errors: list = []
        findings = _build_findings(
            fetcher, self._anom_df(2),
            max_attributions=2, days=14, errors=errors,
        )
        # Each anomaly's attribution caught the error internally and produced
        # an unattributed finding. No errors should be raised at the outer level.
        assert len(findings) == 2
        for f in findings:
            assert f["account_id"] is None


# ── fixture-driven integration ────────────────────────────────────────────────


def _load_fixture():
    return json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))


def _fetcher_from_case(case: dict) -> _FakeFetcher:
    fd = case["fetcher_data"]
    return _FakeFetcher(
        account_data=_df(fd.get("service_and_account") or []),
        region_data=_df(fd.get("region") or []),
        usage_data=_df(fd.get("usage_type") or []),
        resource_data=_df(fd.get("top_resources") or []),
    )


@pytest.mark.parametrize("case", _load_fixture()["cases"], ids=lambda c: c["name"])
def test_fixture_cases_attribute_correctly(case):
    fetcher = _fetcher_from_case(case)
    result = attribute_anomaly(fetcher, case["anomaly"])
    expected = case["expected_attribution"]
    assert result["account"] == expected["account"], case["name"]
    assert result["region"] == expected["region"], case["name"]
    assert result["usage_type"] == expected["usage_type"], case["name"]
    assert result["resource_id"] == expected["resource_id"], case["name"]
