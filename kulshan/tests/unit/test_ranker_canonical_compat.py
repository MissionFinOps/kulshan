"""Compatibility test: findings_ranker works with canonical Finding.to_dict() output.

Task 8.2 — Verify that priority(), flatten_findings(), and top_n() accept dicts
produced by Finding.to_dict() without modification.

Requirements: 5.1, 5.2, 5.3, 5.4, 5.5
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from kulshan.findings_ranker import flatten_findings, priority, top_n
from kulshan.models import Finding, Severity, SEVERITY_SCORE_IMPACT


def _canonical_finding(**overrides) -> Finding:
    """Build a valid canonical Finding with sensible defaults."""
    defaults = {
        "id": "cost-anomaly_statistical-abcdef0123456789",
        "pack": "cost",
        "kind": "anomaly_statistical",
        "fingerprint": "abcdef0123456789",
        "title": "EC2 cost spike in us-east-1",
        "severity": Severity.HIGH,
        "score_impact": SEVERITY_SCORE_IMPACT["high"],
        "estimated_monthly_impact": 4500.0,
        "confidence": 0.85,
        "effort": "medium",
        "risk": "safe",
        "account_id": "123456789012",
        "region": "us-east-1",
        "description": "Cost is 180% above baseline",
        "evidence": {"z_score": 3.2},
        "recommended_action": "Review recent EC2 provisioning",
        "detected_at": datetime(2026, 5, 1, tzinfo=timezone.utc),
        "schema_version": "2.0",
    }
    defaults.update(overrides)
    return Finding(**defaults)


class TestRankerCanonicalCompatibility:
    """Verify findings_ranker.py works with canonical Finding.to_dict() output."""

    def test_priority_accepts_canonical_to_dict(self):
        """priority() computes a valid score from a canonical to_dict() output."""
        finding = _canonical_finding()
        d = finding.to_dict()
        score = priority(d)
        assert isinstance(score, float)
        assert 0.0 <= score <= 1.0

    def test_priority_uses_correct_keys_from_to_dict(self):
        """Confirm priority() reads the exact keys that to_dict() produces."""
        # Critical severity, max impact, perfect confidence, trivial effort, safe risk
        # should yield highest possible priority
        finding = _canonical_finding(
            severity=Severity.CRITICAL,
            score_impact=SEVERITY_SCORE_IMPACT["critical"],
            estimated_monthly_impact=50000.0,
            confidence=1.0,
            effort="trivial",
            risk="safe",
        )
        d = finding.to_dict()
        score = priority(d)
        assert score == pytest.approx(1.0, abs=0.001)

    def test_priority_low_values_from_to_dict(self):
        """Info severity, no impact, zero confidence → near-zero priority."""
        finding = _canonical_finding(
            severity=Severity.INFO,
            score_impact=SEVERITY_SCORE_IMPACT["info"],
            estimated_monthly_impact=0.0,
            confidence=0.0,
            effort="high",
            risk="high",
        )
        d = finding.to_dict()
        score = priority(d)
        assert score == pytest.approx(0.0, abs=0.001)

    def test_priority_all_severity_levels(self):
        """All canonical severity values are recognized by the ranker."""
        for sev in Severity:
            finding = _canonical_finding(
                severity=sev,
                score_impact=SEVERITY_SCORE_IMPACT[sev.value],
            )
            d = finding.to_dict()
            score = priority(d)
            assert isinstance(score, float)
            assert 0.0 <= score <= 1.0

    def test_priority_all_effort_levels(self):
        """All canonical effort values are recognized by the ranker."""
        for effort in ("trivial", "low", "medium", "high"):
            finding = _canonical_finding(effort=effort)
            d = finding.to_dict()
            score = priority(d)
            assert isinstance(score, float)
            assert 0.0 <= score <= 1.0

    def test_priority_all_risk_levels(self):
        """All canonical risk values are recognized by the ranker."""
        for risk in ("safe", "low", "medium", "high"):
            finding = _canonical_finding(risk=risk)
            d = finding.to_dict()
            score = priority(d)
            assert isinstance(score, float)
            assert 0.0 <= score <= 1.0

    def test_flatten_findings_with_canonical_dicts(self):
        """flatten_findings() correctly extracts to_dict() outputs from results."""
        f1 = _canonical_finding(id="cost-a-1111111111111111", kind="a", fingerprint="1111111111111111")
        f2 = _canonical_finding(id="security-b-2222222222222222", pack="security", kind="b", fingerprint="2222222222222222")
        f3 = _canonical_finding(id="sweep-c-3333333333333333", pack="sweep", kind="c", fingerprint="3333333333333333")

        results = {
            "cost": {"findings": [f1.to_dict(), f2.to_dict()]},
            "security": {"findings": [f3.to_dict()]},
        }
        out = flatten_findings(results)
        assert len(out) == 3
        assert {f["id"] for f in out} == {
            "cost-a-1111111111111111",
            "security-b-2222222222222222",
            "sweep-c-3333333333333333",
        }

    def test_top_n_with_canonical_dicts(self):
        """top_n() correctly ranks canonical to_dict() outputs."""
        high_priority = _canonical_finding(
            id="cost-crit-aaaaaaaaaaaaaaaa",
            kind="crit",
            fingerprint="aaaaaaaaaaaaaaaa",
            severity=Severity.CRITICAL,
            score_impact=SEVERITY_SCORE_IMPACT["critical"],
            estimated_monthly_impact=9000.0,
            confidence=0.95,
            effort="trivial",
            risk="safe",
        )
        low_priority = _canonical_finding(
            id="cost-info-bbbbbbbbbbbbbbbb",
            kind="info",
            fingerprint="bbbbbbbbbbbbbbbb",
            severity=Severity.INFO,
            score_impact=SEVERITY_SCORE_IMPACT["info"],
            estimated_monthly_impact=10.0,
            confidence=0.3,
            effort="high",
            risk="high",
        )
        findings = [low_priority.to_dict(), high_priority.to_dict()]
        ranked = top_n(findings, n=10)

        assert len(ranked) == 2
        assert ranked[0]["id"] == "cost-crit-aaaaaaaaaaaaaaaa"
        assert ranked[1]["id"] == "cost-info-bbbbbbbbbbbbbbbb"

    def test_top_n_deterministic_with_canonical_dicts(self):
        """Repeated calls with same canonical dicts produce same order."""
        findings = []
        for i in range(5):
            fp = f"{i:016d}"
            f = _canonical_finding(
                id=f"cost-k{i}-{fp}",
                kind=f"k{i}",
                fingerprint=fp,
                estimated_monthly_impact=float(i * 1000),
            )
            findings.append(f.to_dict())

        a = top_n(findings, n=3)
        b = top_n(findings, n=3)
        assert [f["id"] for f in a] == [f["id"] for f in b]

    def test_top_n_respects_n_limit_with_canonical_dicts(self):
        """top_n returns at most n items from canonical findings."""
        findings = []
        for i in range(20):
            fp = f"{i:016d}"
            f = _canonical_finding(
                id=f"cost-k{i}-{fp}",
                kind=f"k{i}",
                fingerprint=fp,
                estimated_monthly_impact=float(i * 100),
            )
            findings.append(f.to_dict())

        out = top_n(findings, n=5)
        assert len(out) == 5

    def test_severity_field_is_string_not_enum(self):
        """to_dict() serializes severity as a string, which the ranker expects."""
        finding = _canonical_finding(severity=Severity.HIGH)
        d = finding.to_dict()
        # The ranker looks up severity as a string in SEVERITY_WEIGHT
        assert isinstance(d["severity"], str)
        assert d["severity"] == "high"

    def test_confidence_field_is_float(self):
        """to_dict() preserves confidence as a float, which the ranker expects."""
        finding = _canonical_finding(confidence=0.85)
        d = finding.to_dict()
        assert isinstance(d["confidence"], float)
        assert d["confidence"] == 0.85

    def test_estimated_monthly_impact_is_float(self):
        """to_dict() preserves estimated_monthly_impact as float."""
        finding = _canonical_finding(estimated_monthly_impact=4500.0)
        d = finding.to_dict()
        assert isinstance(d["estimated_monthly_impact"], float)
        assert d["estimated_monthly_impact"] == 4500.0
