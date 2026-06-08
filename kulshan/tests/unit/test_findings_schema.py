"""Unit tests for the normalized Finding schema.

Phase 6A. Locks the contract that every check pack will eventually emit findings
through. Cost is the only emitter today.
"""
from __future__ import annotations

import json
from datetime import date, datetime

import pytest

from kulshan.models import (
    Finding,
    Severity,
    SEVERITY_SCORE_IMPACT,
    VALID_EFFORT,
    VALID_RISK,
    VALID_SEVERITY,
    _iso_week,
    _json_safe,
    compute_fingerprint,
    make_finding_id,
)


def _valid(**overrides) -> dict:
    base = dict(
        id="cost-anomaly_statistical-abc1234567890def",
        pack="cost",
        kind="anomaly_statistical",
        fingerprint="abc1234567890def",
        title="EC2 - Other spike, 78% in account 000000000000",
        severity=Severity.MEDIUM,
        score_impact=-5,
        estimated_monthly_impact=120.50,
        confidence=0.75,
        effort="medium",
        risk="safe",
    )
    base.update(overrides)
    return base


# ── construction ──────────────────────────────────────────────────────────────


class TestFindingDataclass:
    def test_minimal_finding_constructs(self):
        f = Finding(**_valid())
        assert f.pack == "cost"
        assert f.severity == Severity.MEDIUM
        assert f.score_impact == -5
        assert f.account_id is None  # optional defaults
        assert f.evidence == {}

    def test_full_finding_constructs(self):
        f = Finding(
            **_valid(
                account_id="000000000000",
                region="us-east-1",
                service="EC2 - Other",
                resource_arn="arn:aws:ec2:us-east-1:000000000000:instance/i-0aaaa1234567890ab",
                evidence={"date": "2026-04-15", "z_score": 4.1},
                description="Cost is 98% above baseline.",
                recommended_action="Investigate in account 000000000000.",
            )
        )
        assert f.account_id == "000000000000"
        assert f.evidence["z_score"] == 4.1

    def test_severity_validation_rejects_unknown(self):
        with pytest.raises(ValueError, match="severity"):
            Finding(**_valid(severity="MAJOR"))

    def test_effort_validation_rejects_unknown(self):
        with pytest.raises(ValueError, match="effort"):
            Finding(**_valid(effort="enormous"))

    def test_risk_validation_rejects_unknown(self):
        with pytest.raises(ValueError, match="risk"):
            Finding(**_valid(risk="catastrophic"))

    def test_confidence_must_be_in_range(self):
        with pytest.raises(ValueError, match="confidence"):
            Finding(**_valid(confidence=1.5))
        with pytest.raises(ValueError, match="confidence"):
            Finding(**_valid(confidence=-0.1))

    def test_finding_is_hashable_when_evidence_omitted(self):
        # frozen=True on a dataclass with mutable default factory still works for hashing
        # if the user constructed it; but evidence is a dict (mutable) so equality is enough.
        f1 = Finding(**_valid())
        f2 = Finding(**_valid())
        assert f1 == f2  # value-equal


# ── to_dict / JSON safety ─────────────────────────────────────────────────────


class TestToDict:
    def test_to_dict_round_trips_through_json(self):
        f = Finding(
            **_valid(
                evidence={"spike": 4.2, "n": 3},
            )
        )
        d = f.to_dict()
        s = json.dumps(d)  # must be JSON-safe
        loaded = json.loads(s)
        assert loaded["pack"] == "cost"
        assert loaded["evidence"]["spike"] == 4.2

    def test_to_dict_handles_nested_lists(self):
        f = Finding(
            **_valid(
                evidence={"notes": ["a", "b", "c"]}
            )
        )
        d = f.to_dict()
        json.dumps(d)
        assert d["evidence"]["notes"] == ["a", "b", "c"]


class TestJsonSafe:
    def test_handles_primitives(self):
        for v in (None, "", "x", 1, 1.5, True, False):
            assert _json_safe(v) == v

    def test_coerces_dates(self):
        assert _json_safe(date(2026, 4, 15)) == "2026-04-15"
        assert _json_safe(datetime(2026, 4, 15, 12)).startswith("2026-04-15")

    def test_handles_dict_keys_to_str(self):
        out = _json_safe({1: "one", "two": 2})
        assert out == {"1": "one", "two": 2}


# ── fingerprint ───────────────────────────────────────────────────────────────


class TestFingerprintStability:
    def test_same_inputs_same_fingerprint(self):
        kw = dict(
            pack="cost",
            kind="anomaly_statistical",
            account="000000000000",
            service="EC2 - Other",
            usage_type="USE1-NatGateway-Bytes",
            period=date(2026, 4, 15),
        )
        assert compute_fingerprint(**kw) == compute_fingerprint(**kw)
        assert len(compute_fingerprint(**kw)) == 16

    def test_different_account_different_fingerprint(self):
        base = dict(
            pack="cost", kind="anomaly_statistical",
            service="EC2", usage_type="X", period=date(2026, 4, 15),
        )
        a = compute_fingerprint(account="000000000000", **base)
        b = compute_fingerprint(account="111111111111", **base)
        assert a != b

    def test_different_service_different_fingerprint(self):
        base = dict(
            pack="cost", kind="anomaly_statistical",
            account="000000000000", usage_type="X", period=date(2026, 4, 15),
        )
        a = compute_fingerprint(service="EC2", **base)
        b = compute_fingerprint(service="S3", **base)
        assert a != b

    def test_none_account_or_usage_does_not_explode(self):
        assert compute_fingerprint(
            pack="cost", kind="x", account=None, service="EC2",
            usage_type=None, period=date(2026, 4, 15),
        )

    def test_iso_week_granularity_collapses_within_week(self):
        # 2026-04-13 (Mon) and 2026-04-17 (Fri) are in the same ISO week.
        base = dict(
            pack="cost", kind="anomaly_statistical", account=None,
            service="X", usage_type="Y",
        )
        a = compute_fingerprint(period=date(2026, 4, 13), **base)
        b = compute_fingerprint(period=date(2026, 4, 17), **base)
        assert a == b, "fingerprints within the same ISO week must match"

    def test_iso_week_distinguishes_across_weeks(self):
        base = dict(
            pack="cost", kind="anomaly_statistical", account=None,
            service="X", usage_type="Y",
        )
        a = compute_fingerprint(period=date(2026, 4, 13), **base)
        b = compute_fingerprint(period=date(2026, 4, 21), **base)
        assert a != b


class TestIsoWeekHelper:
    def test_string_iso_date(self):
        assert _iso_week("2026-04-15") == "2026-W16"

    def test_handles_none(self):
        assert _iso_week(None) == ""

    def test_handles_empty_string(self):
        assert _iso_week("") == ""

    def test_datetime_input(self):
        assert _iso_week(datetime(2026, 4, 15, 10, 30)) == "2026-W16"

    def test_date_input(self):
        assert _iso_week(date(2026, 4, 15)) == "2026-W16"

    def test_invalid_string_returns_as_is(self):
        # Don't crash on garbage input; preserve raw value.
        assert _iso_week("not-a-date") == "not-a-date"


# ── score_impact severity table ───────────────────────────────────────────────


class TestSeverityImpactTable:
    def test_table_values(self):
        # Phase 6 Q4: locked values.
        assert SEVERITY_SCORE_IMPACT["critical"] == -15
        assert SEVERITY_SCORE_IMPACT["high"] == -10
        assert SEVERITY_SCORE_IMPACT["medium"] == -5
        assert SEVERITY_SCORE_IMPACT["low"] == -2
        assert SEVERITY_SCORE_IMPACT["info"] == 0

    def test_all_valid_severities_have_impact(self):
        for sev in VALID_SEVERITY:
            assert sev in SEVERITY_SCORE_IMPACT

    def test_valid_vocabularies(self):
        # Lock the canonical vocabularies so packs cannot quietly drift.
        assert VALID_SEVERITY == ("critical", "high", "medium", "low", "info")
        assert VALID_EFFORT == ("trivial", "low", "medium", "high")
        assert VALID_RISK == ("safe", "low", "medium", "high")


# ── id helper ─────────────────────────────────────────────────────────────────


class TestMakeFindingId:
    def test_format(self):
        fp = "abc1234567890def"
        result = make_finding_id(pack="cost", kind="anomaly_statistical", fingerprint=fp)
        assert result == f"cost-anomaly_statistical-{fp}"


# ── fixture sanity (no real account ids) ──────────────────────────────────────


def test_no_real_account_ids_in_fixture_file():
    """The shared attribution fixture must use only placeholder 12-digit IDs."""
    import re
    from pathlib import Path

    fixture = (
        Path(__file__).resolve().parents[1]
        / "fixtures"
        / "cost"
        / "anomaly_attribution_cases.json"
    )
    text = fixture.read_text(encoding="utf-8")

    # Allow only these placeholder IDs as 12-digit numbers.
    allowed = {"000000000000", "111111111111", "222222222222"}
    found = re.findall(r"\b\d{12}\b", text)
    assert found, "fixture should contain at least one placeholder account ID"
    leaked = [f for f in found if f not in allowed]
    assert not leaked, f"fixture contains non-placeholder 12-digit IDs: {leaked}"
