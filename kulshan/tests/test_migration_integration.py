"""
Integration tests for the end-to-end consistency-normalization pipeline.

Tests the full data flow: pack → adapter → validation → flatten → rank,
including JSON round-trip serialization and cross-pack ranking.

Validates: Requirements 3.1, 5.1, 8.1, 8.2
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Dict, List
from unittest.mock import patch, MagicMock

import pytest

from kulshan.adapter import adapt
from kulshan.findings_ranker import flatten_findings, priority, top_n
from kulshan.models import (
    Finding,
    Severity,
    SEVERITY_SCORE_IMPACT,
    compute_fingerprint,
    make_finding_id,
)
from kulshan.orchestrator import run_all_scans, validate_finding


# ---------------------------------------------------------------------------
# Helpers: build mock findings for various packs
# ---------------------------------------------------------------------------


def _make_canonical_cost_finding(idx: int) -> dict:
    """Create a canonical cost finding dict."""
    fingerprint = compute_fingerprint(
        pack="cost",
        kind="anomaly_statistical",
        account="123456789012",
        service="Amazon EC2",
        usage_type=f"BoxUsage:t3.medium-{idx}",
        period="2026-05-01",
    )
    return {
        "id": make_finding_id(pack="cost", kind="anomaly_statistical", fingerprint=fingerprint),
        "pack": "cost",
        "kind": "anomaly_statistical",
        "fingerprint": fingerprint,
        "title": f"EC2 cost spike #{idx}",
        "severity": "high",
        "score_impact": SEVERITY_SCORE_IMPACT["high"],
        "estimated_monthly_impact": 1000.0 + idx * 500.0,
        "confidence": 0.85,
        "effort": "medium",
        "risk": "safe",
        "account_id": "123456789012",
        "region": "us-east-1",
        "resource_arn": None,
        "resource_type": None,
        "service": "Amazon EC2",
        "description": f"Cost is {150 + idx * 10}% above baseline",
        "evidence": {"z_score": 3.2 + idx * 0.1},
        "recommended_action": "Review recent EC2 provisioning",
        "compliance_frameworks": [],
        "detected_at": "2026-05-01T00:00:00+00:00",
        "schema_version": "2.0",
    }


def _make_canonical_security_finding(idx: int) -> dict:
    """Create a canonical security finding dict."""
    fingerprint = compute_fingerprint(
        pack="security",
        kind="iam",
        account="123456789012",
        service="IAM",
        usage_type=None,
        period="2026-05-01",
    )
    # Make fingerprint unique per idx by appending idx to kind
    kind = f"iam_check_{idx}"
    fingerprint = compute_fingerprint(
        pack="security",
        kind=kind,
        account="123456789012",
        service="IAM",
        usage_type=None,
        period="2026-05-01",
    )
    return {
        "id": make_finding_id(pack="security", kind=kind, fingerprint=fingerprint),
        "pack": "security",
        "kind": kind,
        "fingerprint": fingerprint,
        "title": f"IAM policy too permissive #{idx}",
        "severity": "critical" if idx == 0 else "medium",
        "score_impact": SEVERITY_SCORE_IMPACT["critical" if idx == 0 else "medium"],
        "estimated_monthly_impact": 0.0,
        "confidence": 0.95,
        "effort": "low",
        "risk": "medium",
        "account_id": "123456789012",
        "region": "us-east-1",
        "resource_arn": f"arn:aws:iam::123456789012:policy/overly-permissive-{idx}",
        "resource_type": "AWS::IAM::Policy",
        "service": "IAM",
        "description": f"Policy grants * on all resources (check {idx})",
        "evidence": {"actions_granted": ["*"]},
        "recommended_action": "Scope down policy to least privilege",
        "compliance_frameworks": ["CIS 1.16", "NIST AC-6"],
        "detected_at": "2026-05-01T00:00:00+00:00",
        "schema_version": "2.0",
    }


def _make_legacy_finding(idx: int) -> dict:
    """Create a legacy-shaped finding (v1.0 / old models.py shape)."""
    return {
        "tool": "sweep",
        "check_id": f"orphan_ebs_{idx}",
        "title": f"Orphaned EBS volume #{idx}",
        "severity": "low",
        "confidence": "medium",  # enum string, not float
        "monthly_impact_usd": "25.50",  # Decimal string
        "effort_minutes": 10,
        "account": "123456789012",
        "region": "us-west-2",
        "resource_id": f"vol-0abc{idx:04d}",
        "resource_type": "AWS::EC2::Volume",
        "service": "Amazon EBS",
        "why_it_matters": "Volume is unattached and incurring charges",
        "remediation_text": "Delete the unattached volume",
        "custom_field_xyz": f"extra_value_{idx}",
    }


def _make_invalid_finding() -> dict:
    """Create a finding dict that will fail validation."""
    return {
        "id": "bad-finding",
        "pack": "cost",
        "kind": "anomaly",
        "title": "Some title",
        "severity": "INVALID_SEVERITY",  # invalid
        "confidence": 0.5,
        "effort": "medium",
        "risk": "safe",
    }


def _make_mock_pack_result(findings: List[dict], scores: dict | None = None) -> dict:
    """Wrap findings in a pack result structure."""
    if scores is None:
        scores = {
            "overall_score": 85,
            "grade": "B",
            "total_findings": len(findings),
            "severity_counts": {"high": 1, "medium": 1},
        }
    return {
        "tool": "mock",
        "scores": scores,
        "findings": findings,
        "errors": [],
    }


# ---------------------------------------------------------------------------
# Mock pack modules for orchestrator testing
# ---------------------------------------------------------------------------


def _create_mock_check(findings: List[dict], tool_key: str):
    """Create a mock check module that returns specific findings."""
    mock_module = MagicMock()
    mock_module.run_scan.return_value = {
        "tool": tool_key,
        "scores": {
            "overall_score": 80,
            "grade": "B",
            "total_findings": len(findings),
            "severity_counts": {},
        },
        "findings": findings,
        "errors": [],
    }
    return mock_module


# ---------------------------------------------------------------------------
# Test 1: 10-pack orchestrator run with mocked packs
# ---------------------------------------------------------------------------


class TestOrchestratorPipeline:
    """Test orchestrator pipeline with mocked packs returning mix of
    valid/invalid/legacy findings."""

    def test_orchestrator_with_mixed_findings(self):
        """10-pack run with cost emitting canonical, sweep emitting legacy,
        one pack emitting invalid, and other packs with empty findings."""

        # Build findings for specific packs
        cost_findings = [_make_canonical_cost_finding(i) for i in range(3)]
        security_findings = [_make_canonical_security_finding(i) for i in range(2)]
        legacy_findings = [_make_legacy_finding(i) for i in range(2)]
        invalid_findings = [_make_invalid_finding(), _make_canonical_cost_finding(99)]

        # Map of tool_key → mock check module
        mock_checks: Dict[str, Any] = {}
        from kulshan.orchestrator import TOOL_ORDER

        for tool_key in TOOL_ORDER:
            if tool_key == "cost":
                mock_checks[tool_key] = _create_mock_check(cost_findings, tool_key)
            elif tool_key == "security":
                mock_checks[tool_key] = _create_mock_check(security_findings, tool_key)
            elif tool_key == "sweep":
                mock_checks[tool_key] = _create_mock_check(legacy_findings, tool_key)
            elif tool_key == "dr":
                # dr pack returns one invalid + one valid
                mock_checks[tool_key] = _create_mock_check(invalid_findings, tool_key)
            else:
                # Other packs return empty findings
                mock_checks[tool_key] = _create_mock_check([], tool_key)

        def mock_load_check(tool_key: str):
            return mock_checks.get(tool_key)

        # Mock session and console
        mock_session = MagicMock()
        from rich.console import Console
        from io import StringIO

        console = Console(file=StringIO(), force_terminal=False)

        with patch("kulshan.orchestrator._load_check", side_effect=mock_load_check):
            results = run_all_scans(
                session=mock_session,
                regions=["us-east-1"],
                profile=None,
                quick=False,
                console=console,
            )

        # Cost pack: all 3 canonical findings should be valid
        assert len(results["cost"]["findings"]) == 3

        # Security pack: all 2 canonical findings should be valid
        assert len(results["security"]["findings"]) == 2

        # Sweep pack: legacy findings are adapted and should pass validation
        assert len(results["sweep"]["findings"]) == 2
        for f in results["sweep"]["findings"]:
            is_valid, reason = validate_finding(f)
            assert is_valid, f"Adapted sweep finding should be valid: {reason}"
            # Verify adapter mapped fields correctly
            assert f["pack"] == "sweep"
            assert "orphan_ebs" in f["kind"]

        # DR pack: one invalid + one valid = only the valid one survives
        assert len(results["dr"]["findings"]) == 1

        # Other packs: empty findings
        for tool_key in TOOL_ORDER:
            if tool_key not in ("cost", "security", "sweep", "dr"):
                assert results[tool_key]["findings"] == []

    def test_invalid_findings_do_not_crash_pipeline(self):
        """A pack returning entirely invalid findings doesn't crash the scan."""
        invalid_findings = [
            {"not": "a finding"},
            {"id": "", "pack": "", "kind": "", "title": "", "severity": "bad",
             "confidence": "nope", "effort": "what", "risk": "huh"},
            42,  # not even a dict
        ]

        from kulshan.orchestrator import TOOL_ORDER

        mock_checks: Dict[str, Any] = {}
        for tool_key in TOOL_ORDER:
            if tool_key == "cost":
                mock_checks[tool_key] = _create_mock_check(invalid_findings, tool_key)
            else:
                mock_checks[tool_key] = _create_mock_check([], tool_key)

        def mock_load_check(tool_key: str):
            return mock_checks.get(tool_key)

        mock_session = MagicMock()
        from rich.console import Console
        from io import StringIO

        console = Console(file=StringIO(), force_terminal=False)

        with patch("kulshan.orchestrator._load_check", side_effect=mock_load_check):
            results = run_all_scans(
                session=mock_session,
                regions=["us-east-1"],
                console=console,
            )

        # Pipeline completes without error
        assert "cost" in results
        # All invalid findings are excluded
        assert results["cost"]["findings"] == []


# ---------------------------------------------------------------------------
# Test 2: JSON round-trip
# ---------------------------------------------------------------------------


class TestJsonRoundTrip:
    """Test JSON export → reload → all findings reconstruct via Finding.from_dict."""

    def test_serialize_and_reconstruct_all_findings(self):
        """Serialize findings to JSON, reload, and reconstruct via Finding.from_dict."""
        findings = [
            _make_canonical_cost_finding(i) for i in range(5)
        ] + [
            _make_canonical_security_finding(i) for i in range(3)
        ]

        # Serialize to JSON (simulating file export)
        json_str = json.dumps(findings)

        # Reload from JSON
        loaded = json.loads(json_str)

        # Reconstruct each via Finding.from_dict
        reconstructed = []
        for f_dict in loaded:
            finding = Finding.from_dict(f_dict)
            reconstructed.append(finding)

        assert len(reconstructed) == 8

        # Verify round-trip: to_dict → from_dict → to_dict should match
        for original_dict, finding in zip(findings, reconstructed):
            round_tripped = finding.to_dict()
            # Key fields should survive the round trip
            assert round_tripped["id"] == original_dict["id"]
            assert round_tripped["pack"] == original_dict["pack"]
            assert round_tripped["kind"] == original_dict["kind"]
            assert round_tripped["fingerprint"] == original_dict["fingerprint"]
            assert round_tripped["severity"] == original_dict["severity"]
            assert round_tripped["confidence"] == original_dict["confidence"]
            assert round_tripped["effort"] == original_dict["effort"]
            assert round_tripped["risk"] == original_dict["risk"]
            assert round_tripped["estimated_monthly_impact"] == original_dict["estimated_monthly_impact"]
            assert round_tripped["schema_version"] == original_dict["schema_version"]

    def test_json_round_trip_with_adapted_legacy_findings(self):
        """Legacy findings adapted → serialized → deserialized should reconstruct."""
        legacy_findings = [_make_legacy_finding(i) for i in range(3)]

        # Adapt legacy findings
        adapted = [adapt("sweep", f) for f in legacy_findings]

        # Verify adapted findings pass validation
        for f in adapted:
            is_valid, reason = validate_finding(f)
            assert is_valid, f"Adapted finding should be valid: {reason}"

        # JSON round-trip
        json_str = json.dumps(adapted)
        loaded = json.loads(json_str)

        # Reconstruct each
        for f_dict in loaded:
            finding = Finding.from_dict(f_dict)
            # Verify core fields
            assert finding.pack == "sweep"
            assert "orphan_ebs" in finding.kind
            assert finding.effort == "trivial"  # 10 minutes → trivial
            assert isinstance(finding.confidence, float)
            assert 0.0 <= finding.confidence <= 1.0

    def test_full_scan_results_json_export_and_reload(self):
        """Simulate full scan results export and reload."""
        # Build results dict as orchestrator would produce
        results = {
            "cost": {
                "findings": [_make_canonical_cost_finding(i) for i in range(3)],
                "scores": {"overall_score": 75},
                "errors": [],
            },
            "security": {
                "findings": [_make_canonical_security_finding(i) for i in range(2)],
                "scores": {"overall_score": 60},
                "errors": [],
            },
            "sweep": {
                "findings": [],
                "scores": {"overall_score": 95},
                "errors": [],
            },
        }

        # JSON export
        json_str = json.dumps(results)

        # Reload
        loaded_results = json.loads(json_str)

        # Reconstruct all findings
        all_findings = []
        for pack_name, pack_result in loaded_results.items():
            for f_dict in pack_result.get("findings", []):
                finding = Finding.from_dict(f_dict)
                all_findings.append(finding)
                assert finding.pack == pack_name

        assert len(all_findings) == 5  # 3 cost + 2 security


# ---------------------------------------------------------------------------
# Test 3: Cross-pack ranking with top_n
# ---------------------------------------------------------------------------


class TestCrossPackRanking:
    """Test top_n works with findings from multiple packs (cost + security)."""

    def test_top_n_ranks_across_cost_and_security_packs(self):
        """top_n ranks findings from both cost and security by composite priority."""
        cost_findings = [_make_canonical_cost_finding(i) for i in range(5)]
        security_findings = [_make_canonical_security_finding(i) for i in range(3)]

        all_findings = cost_findings + security_findings

        # Get top 5
        top5 = top_n(all_findings, 5)

        assert len(top5) == 5

        # Verify priority is non-increasing
        for i in range(len(top5) - 1):
            assert priority(top5[i]) >= priority(top5[i + 1])

        # The critical security finding (idx=0) should rank high
        # since it has critical severity (weight 1.0) and high confidence (0.95)
        top_packs = [f["pack"] for f in top5]
        assert "security" in top_packs, "Critical security finding should appear in top 5"

    def test_top_n_with_flatten_findings(self):
        """flatten_findings → top_n pipeline works with mixed pack results."""
        results = {
            "cost": {
                "findings": [_make_canonical_cost_finding(i) for i in range(4)],
            },
            "security": {
                "findings": [_make_canonical_security_finding(i) for i in range(3)],
            },
            "sweep": {
                "findings": [],
            },
            "dr": {
                "findings": None,  # simulate pack with None findings
            },
        }

        # Flatten
        flat = flatten_findings(results)
        assert len(flat) == 7  # 4 cost + 3 security (sweep empty, dr None skipped)

        # Rank
        top3 = top_n(flat, 3)
        assert len(top3) == 3

        # Each finding in top3 should be a valid finding dict
        for f in top3:
            is_valid, reason = validate_finding(f)
            assert is_valid, f"Top finding should be valid: {reason}"

    def test_top_n_deterministic_across_packs(self):
        """Repeated top_n calls with same mixed-pack input produce same order."""
        all_findings = (
            [_make_canonical_cost_finding(i) for i in range(3)]
            + [_make_canonical_security_finding(i) for i in range(3)]
        )

        result1 = top_n(all_findings, 4)
        result2 = top_n(all_findings, 4)

        assert result1 == result2


# ---------------------------------------------------------------------------
# Test 4: Full pipeline (pack → adapter → validation → flatten → rank)
# ---------------------------------------------------------------------------


class TestFullPipeline:
    """Test the complete data flow from pack output through ranking."""

    def test_end_to_end_pack_to_ranking(self):
        """Full pipeline: pack results → adapt legacy → validate → flatten → rank."""
        # Simulated pack outputs (as run_all_scans would receive them)
        cost_findings = [_make_canonical_cost_finding(i) for i in range(3)]
        security_findings = [_make_canonical_security_finding(i) for i in range(2)]
        legacy_findings = [_make_legacy_finding(i) for i in range(2)]

        # Step 1: Adapt legacy findings (as orchestrator does)
        adapted_legacy = [adapt("sweep", f) for f in legacy_findings]

        # Step 2: Validate all findings
        all_candidate_findings = cost_findings + security_findings + adapted_legacy
        valid_findings = []
        for f in all_candidate_findings:
            is_valid, reason = validate_finding(f)
            if is_valid:
                valid_findings.append(f)

        # All should be valid after proper construction/adaptation
        assert len(valid_findings) == 7

        # Step 3: Flatten (simulate results dict structure)
        results = {
            "cost": {"findings": cost_findings},
            "security": {"findings": security_findings},
            "sweep": {"findings": adapted_legacy},
        }
        flat = flatten_findings(results)
        assert len(flat) == 7

        # Step 4: Rank
        ranked = top_n(flat, 5)
        assert len(ranked) == 5

        # Verify ranking properties
        for i in range(len(ranked) - 1):
            assert priority(ranked[i]) >= priority(ranked[i + 1])

        # All ranked findings should be valid
        for f in ranked:
            is_valid, reason = validate_finding(f)
            assert is_valid, f"Ranked finding must be valid: {reason}"

    def test_pipeline_with_all_empty_packs(self):
        """Pipeline handles all packs returning empty findings gracefully."""
        results = {tool: {"findings": []} for tool in
                   ["cost", "security", "sweep", "dr", "age",
                    "drift", "tag", "pulse", "limit", "topo"]}

        flat = flatten_findings(results)
        assert flat == []

        ranked = top_n(flat, 10)
        assert ranked == []

    def test_pipeline_resilience_to_mixed_invalid(self):
        """Pipeline drops invalid findings but preserves valid ones from same pack."""
        # Mix of valid and invalid in same pack
        valid_cost = _make_canonical_cost_finding(0)
        invalid = {"id": "x", "pack": "cost", "kind": "y", "title": "z",
                   "severity": "bogus", "confidence": 0.5, "effort": "medium", "risk": "safe"}
        valid_cost_2 = _make_canonical_cost_finding(1)

        all_findings = [valid_cost, invalid, valid_cost_2]

        # Validate and filter (as orchestrator does)
        valid = [f for f in all_findings if validate_finding(f)[0]]
        assert len(valid) == 2

        # Rank
        ranked = top_n(valid, 10)
        assert len(ranked) == 2

    def test_adapted_findings_integrate_with_ranking(self):
        """Adapted legacy findings participate correctly in cross-pack ranking."""
        # A high-impact legacy finding should rank appropriately
        legacy = {
            "tool": "sweep",
            "check_id": "unused_nat_gateway",
            "title": "Unused NAT Gateway costing $45/day",
            "severity": "high",
            "confidence": "high",  # enum → 0.85
            "monthly_impact_usd": "1350.00",
            "effort_minutes": 5,  # → trivial
            "account": "123456789012",
            "region": "us-east-1",
            "resource_id": "nat-0abc1234",
            "service": "Amazon VPC",
        }

        adapted = adapt("sweep", legacy)
        is_valid, reason = validate_finding(adapted)
        assert is_valid, f"Adapted finding should be valid: {reason}"

        # Compare priority with a medium-severity cost finding
        cost_finding = _make_canonical_cost_finding(0)  # high sev, $1000 impact

        # The adapted finding has high severity, high confidence, $1350 impact, trivial effort
        # → should have a high priority score
        adapted_priority = priority(adapted)
        assert 0.0 <= adapted_priority <= 1.0

        # Rank them together
        ranked = top_n([adapted, cost_finding], 2)
        assert len(ranked) == 2
        # Both should be present regardless of order
        ranked_ids = {f["id"] for f in ranked}
        assert adapted["id"] in ranked_ids
        assert cost_finding["id"] in ranked_ids
