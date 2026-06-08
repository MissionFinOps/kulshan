"""Unit tests for the composite findings ranker (Phase 6C-1)."""
from __future__ import annotations

import pytest

from kulshan.findings_ranker import (
    EFFORT_WEIGHT,
    IMPACT_CAP,
    RISK_WEIGHT,
    SEVERITY_WEIGHT,
    flatten_findings,
    priority,
    top_n,
)


def _f(**overrides) -> dict:
    """Build a minimal valid finding dict for ranker tests."""
    base = {
        "id": "cost-anomaly_statistical-0000000000000000",
        "pack": "cost",
        "kind": "anomaly_statistical",
        "severity": "medium",
        "estimated_monthly_impact": 1000.0,
        "confidence": 0.75,
        "effort": "medium",
        "risk": "safe",
    }
    base.update(overrides)
    return base


# ── priority ──────────────────────────────────────────────────────────────────


class TestPriority:
    def test_returns_float_in_zero_to_one_range(self):
        result = priority(_f())
        assert isinstance(result, float)
        assert 0.0 <= result <= 1.0

    def test_higher_impact_higher_priority(self):
        a = priority(_f(estimated_monthly_impact=100.0))
        b = priority(_f(estimated_monthly_impact=5000.0))
        assert b > a

    def test_higher_severity_higher_priority(self):
        a = priority(_f(severity="low"))
        b = priority(_f(severity="critical"))
        assert b > a

    def test_higher_confidence_higher_priority(self):
        a = priority(_f(confidence=0.50))
        b = priority(_f(confidence=0.95))
        assert b > a

    def test_lower_effort_higher_priority(self):
        a = priority(_f(effort="high"))
        b = priority(_f(effort="trivial"))
        assert b > a

    def test_lower_risk_higher_priority(self):
        a = priority(_f(risk="high"))
        b = priority(_f(risk="safe"))
        assert b > a

    def test_impact_cap_clamps_extreme_values(self):
        cap_value = priority(_f(estimated_monthly_impact=IMPACT_CAP))
        beyond = priority(_f(estimated_monthly_impact=IMPACT_CAP * 1000))
        assert cap_value == beyond, "impact above the cap must not influence priority"

    def test_negative_impact_treated_as_zero(self):
        a = priority(_f(estimated_monthly_impact=-500.0))
        b = priority(_f(estimated_monthly_impact=0.0))
        assert a == b

    def test_missing_fields_default_safely(self):
        # Dict with only id; everything else missing → must not blow up.
        result = priority({"id": "x"})
        assert isinstance(result, float)
        assert 0.0 <= result <= 1.0

    def test_unknown_severity_treated_as_info(self):
        a = priority(_f(severity="UNKNOWN"))
        b = priority(_f(severity="info"))
        assert a == b

    def test_unknown_effort_treated_as_medium(self):
        a = priority(_f(effort="UNKNOWN"))
        b = priority(_f(effort="medium"))
        assert a == b

    def test_unknown_risk_treated_as_safe(self):
        a = priority(_f(risk="UNKNOWN"))
        b = priority(_f(risk="safe"))
        assert a == b

    def test_invalid_confidence_clamped(self):
        # confidence > 1.0 clamped to 1.0; < 0 clamped to 0.
        a = priority(_f(confidence=2.0))
        b = priority(_f(confidence=1.0))
        assert a == b

    def test_weights_constants(self):
        # Lock the canonical mappings.
        assert SEVERITY_WEIGHT["critical"] == 1.0
        assert SEVERITY_WEIGHT["info"] == 0.0
        assert EFFORT_WEIGHT["trivial"] == 0.0
        assert EFFORT_WEIGHT["high"] == 1.0
        assert RISK_WEIGHT["safe"] == 0.0
        assert RISK_WEIGHT["high"] == 1.0


# ── flatten_findings ──────────────────────────────────────────────────────────


class TestFlattenFindings:
    def test_walks_all_packs(self):
        results = {
            "cost": {"findings": [_f(id="c1"), _f(id="c2")]},
            "security": {"findings": [_f(id="s1")]},
        }
        out = flatten_findings(results)
        assert len(out) == 3
        ids = {f["id"] for f in out}
        assert ids == {"c1", "c2", "s1"}

    def test_handles_missing_findings_key(self):
        # Pack with no findings key (older fixtures) contributes nothing.
        results = {
            "cost": {"findings": [_f(id="c1")]},
            "security": {"scores": {}},  # no findings key
        }
        out = flatten_findings(results)
        assert len(out) == 1

    def test_handles_none_findings(self):
        # Pack explicitly returning findings=None.
        results = {
            "cost": {"findings": None},
            "security": {"findings": [_f(id="s1")]},
        }
        out = flatten_findings(results)
        assert len(out) == 1

    def test_ignores_non_dict_entries(self):
        results = {
            "cost": {"findings": [_f(id="c1"), "garbage", None, 42]},
        }
        out = flatten_findings(results)
        assert len(out) == 1

    def test_ignores_non_dict_pack_results(self):
        results = {
            "cost": "not a dict",
            "security": {"findings": [_f(id="s1")]},
        }
        out = flatten_findings(results)
        assert len(out) == 1

    def test_empty_results(self):
        assert flatten_findings({}) == []

    def test_non_dict_results_returns_empty(self):
        assert flatten_findings(None) == []
        assert flatten_findings([]) == []


# ── top_n ─────────────────────────────────────────────────────────────────────


class TestTopN:
    def test_empty_input(self):
        assert top_n([]) == []

    def test_negative_n_returns_empty(self):
        assert top_n([_f()], n=-1) == []

    def test_n_zero_returns_empty(self):
        assert top_n([_f(), _f()], n=0) == []

    def test_returns_at_most_n(self):
        items = [_f(id=f"f{i}") for i in range(20)]
        out = top_n(items, n=10)
        assert len(out) == 10

    def test_returns_all_when_fewer_than_n(self):
        items = [_f(id="f0"), _f(id="f1")]
        out = top_n(items, n=10)
        assert len(out) == 2

    def test_orders_by_priority_descending(self):
        items = [
            _f(id="low_impact", estimated_monthly_impact=100.0, severity="info"),
            _f(id="big_critical", estimated_monthly_impact=9000.0, severity="critical"),
            _f(id="medium", estimated_monthly_impact=2000.0, severity="medium"),
        ]
        out = top_n(items, n=10)
        # Highest priority first.
        assert out[0]["id"] == "big_critical"
        assert out[-1]["id"] == "low_impact"

    def test_deterministic_tie_break_on_impact(self):
        # Same severity/confidence/effort/risk; differ only by impact.
        items = [
            _f(id="A", estimated_monthly_impact=1000.0),
            _f(id="B", estimated_monthly_impact=2000.0),
            _f(id="C", estimated_monthly_impact=1500.0),
        ]
        out = top_n(items, n=10)
        assert [f["id"] for f in out] == ["B", "C", "A"]

    def test_deterministic_tie_break_on_id_when_priority_equal(self):
        # Identical priority + impact → id ascending breaks the tie.
        items = [
            _f(id="zzz", estimated_monthly_impact=1000.0),
            _f(id="aaa", estimated_monthly_impact=1000.0),
            _f(id="mmm", estimated_monthly_impact=1000.0),
        ]
        out = top_n(items, n=10)
        assert [f["id"] for f in out] == ["aaa", "mmm", "zzz"]

    def test_repeated_calls_same_order(self):
        # Determinism: same input must yield identical output.
        items = [_f(id=f"f{i}", estimated_monthly_impact=i * 100.0) for i in range(15)]
        a = top_n(items, n=10)
        b = top_n(items, n=10)
        assert [f["id"] for f in a] == [f["id"] for f in b]
