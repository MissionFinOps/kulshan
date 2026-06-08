"""Unit tests for security pack canonical Finding output.

Verifies that the security pack emits findings in the canonical format
expected by the orchestrator, ranker, and renderers.

Requirements: 10.1, 10.7
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from kulshan.checks.security.scanner.base import (
    Finding as InternalFinding,
    ScanResult as InternalScanResult,
    Severity as InternalSeverity,
)
from kulshan.checks.security import run_scan, _convert_to_canonical
from kulshan.orchestrator import validate_finding


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_internal_finding(
    check_id: str = "IAM-001",
    title: str = "Root account has no MFA",
    severity: InternalSeverity = InternalSeverity.CRITICAL,
    category: str = "Identity & Access",
    resource_type: str = "AWS::IAM::User",
    resource_id: str = "root",
    resource_arn: str = "arn:aws:iam::123456789012:root",
    region: str = "global",
    description: str = "The root account does not have MFA enabled.",
    remediation: str = "Enable MFA on the root account.",
    details: dict | None = None,
) -> InternalFinding:
    """Create an internal scanner Finding for testing."""
    return InternalFinding(
        check_id=check_id,
        title=title,
        severity=severity,
        category=category,
        resource_type=resource_type,
        resource_id=resource_id,
        resource_arn=resource_arn,
        region=region,
        description=description,
        remediation=remediation,
        details=details or {},
    )


def _mock_scanner_class(findings: list[InternalFinding], errors: list[str] | None = None):
    """Create a mock scanner class whose scan() returns the given findings."""
    mock_cls = MagicMock()
    mock_instance = MagicMock()
    mock_instance.scan.return_value = InternalScanResult(
        findings=findings,
        errors=errors or [],
    )
    mock_cls.return_value = mock_instance
    return mock_cls


# ---------------------------------------------------------------------------
# Tests: Findings pass orchestrator validation
# ---------------------------------------------------------------------------

class TestSecurityFindingsPassValidation:
    """Security pack findings must pass orchestrator validate_finding."""

    def test_single_finding_passes_validation(self):
        """A single converted finding passes orchestrator validation."""
        internal = _make_internal_finding()
        canonical = _convert_to_canonical(internal)

        is_valid, reason = validate_finding(canonical)
        assert is_valid, f"Finding failed validation: {reason}"

    def test_all_severity_levels_pass_validation(self):
        """Findings at every severity level pass validation."""
        for sev in InternalSeverity:
            internal = _make_internal_finding(severity=sev)
            canonical = _convert_to_canonical(internal)

            is_valid, reason = validate_finding(canonical)
            assert is_valid, f"Severity {sev.value} failed: {reason}"

    def test_all_scanner_categories_pass_validation(self):
        """Findings from every scanner category pass validation."""
        categories = [
            ("Identity & Access", "IAM-001"),
            ("Network Exposure", "NET-001"),
            ("Data Protection", "DATA-001"),
            ("Compute Security", "COMP-001"),
            ("Logging & Monitoring", "LOG-001"),
            ("Encryption & Secrets", "ENC-001"),
        ]
        for category, check_id in categories:
            internal = _make_internal_finding(
                category=category, check_id=check_id
            )
            canonical = _convert_to_canonical(internal)

            is_valid, reason = validate_finding(canonical)
            assert is_valid, f"Category {category} failed: {reason}"


# ---------------------------------------------------------------------------
# Tests: Severity mapping (uppercase → lowercase)
# ---------------------------------------------------------------------------

class TestSeverityMapping:
    """Internal uppercase Severity enum must map to lowercase canonical values."""

    @pytest.mark.parametrize(
        "internal_sev,expected",
        [
            (InternalSeverity.CRITICAL, "critical"),
            (InternalSeverity.HIGH, "high"),
            (InternalSeverity.MEDIUM, "medium"),
            (InternalSeverity.LOW, "low"),
            (InternalSeverity.INFO, "info"),
        ],
    )
    def test_severity_maps_to_lowercase(self, internal_sev, expected):
        internal = _make_internal_finding(severity=internal_sev)
        canonical = _convert_to_canonical(internal)

        assert canonical["severity"] == expected


# ---------------------------------------------------------------------------
# Tests: Compliance framework population
# ---------------------------------------------------------------------------

class TestComplianceFrameworkPopulation:
    """Compliance frameworks are populated from get_compliance_tags."""

    def test_check_with_compliance_tags(self):
        """IAM-001 has CIS and NIST compliance tags."""
        internal = _make_internal_finding(check_id="IAM-001")
        canonical = _convert_to_canonical(internal)

        assert len(canonical["compliance_frameworks"]) > 0
        # IAM-001 maps to CIS 1.5 and NIST IA-2(1)
        frameworks_str = " ".join(canonical["compliance_frameworks"])
        assert "CIS" in frameworks_str
        assert "NIST" in frameworks_str

    def test_check_without_compliance_tags(self):
        """A check_id with no compliance mapping gets empty list."""
        internal = _make_internal_finding(check_id="UNKNOWN-999")
        canonical = _convert_to_canonical(internal)

        assert canonical["compliance_frameworks"] == []

    def test_compliance_format(self):
        """Compliance entries are formatted as 'Framework ControlId'."""
        internal = _make_internal_finding(check_id="IAM-001")
        canonical = _convert_to_canonical(internal)

        for entry in canonical["compliance_frameworks"]:
            # Each entry should be "Framework ControlId" format
            assert isinstance(entry, str)
            parts = entry.split(" ", 1)
            assert len(parts) == 2, f"Expected 'Framework ControlId', got {entry!r}"


# ---------------------------------------------------------------------------
# Tests: Empty findings case
# ---------------------------------------------------------------------------

class TestEmptyFindings:
    """Security pack returns empty list when no findings detected."""

    @patch("kulshan.checks.security.scanner.iam.IAMScanner")
    @patch("kulshan.checks.security.scanner.network.NetworkScanner")
    @patch("kulshan.checks.security.scanner.data.DataScanner")
    @patch("kulshan.checks.security.scanner.compute.ComputeScanner")
    @patch("kulshan.checks.security.scanner.logging_monitor.LoggingScanner")
    @patch("kulshan.checks.security.scanner.encryption.EncryptionScanner")
    def test_no_findings_returns_empty_list(
        self, mock_enc, mock_log, mock_comp, mock_data, mock_net, mock_iam
    ):
        """When all scanners produce zero findings, findings key is []."""
        for mock_cls in [mock_iam, mock_net, mock_data, mock_comp, mock_log, mock_enc]:
            instance = MagicMock()
            instance.scan.return_value = InternalScanResult(findings=[], errors=[])
            mock_cls.return_value = instance

        session = MagicMock()
        result = run_scan(session, ["us-east-1"])

        assert "findings" in result
        assert result["findings"] == []


# ---------------------------------------------------------------------------
# Tests: Each finding has pack="security"
# ---------------------------------------------------------------------------

class TestPackField:
    """Every finding dict must have pack='security'."""

    def test_finding_has_pack_security(self):
        internal = _make_internal_finding()
        canonical = _convert_to_canonical(internal)

        assert canonical["pack"] == "security"

    def test_all_categories_have_pack_security(self):
        """Findings from any scanner category still have pack=security."""
        categories = [
            "Identity & Access",
            "Network Exposure",
            "Data Protection",
            "Compute Security",
            "Logging & Monitoring",
            "Encryption & Secrets",
        ]
        for category in categories:
            internal = _make_internal_finding(category=category)
            canonical = _convert_to_canonical(internal)
            assert canonical["pack"] == "security"


# ---------------------------------------------------------------------------
# Tests: kind values are valid canonical categories
# ---------------------------------------------------------------------------

class TestKindField:
    """Finding kind must be one of the valid security scanner categories."""

    VALID_KINDS = {"iam", "network", "data", "compute", "logging", "encryption"}

    @pytest.mark.parametrize(
        "category,expected_kind",
        [
            ("Identity & Access", "iam"),
            ("Network Exposure", "network"),
            ("Data Protection", "data"),
            ("Compute Security", "compute"),
            ("Logging & Monitoring", "logging"),
            ("Encryption & Secrets", "encryption"),
        ],
    )
    def test_category_maps_to_kind(self, category, expected_kind):
        internal = _make_internal_finding(category=category)
        canonical = _convert_to_canonical(internal)

        assert canonical["kind"] == expected_kind

    def test_all_kinds_are_valid(self):
        """All mapped kinds are in the valid set."""
        categories = [
            "Identity & Access",
            "Network Exposure",
            "Data Protection",
            "Compute Security",
            "Logging & Monitoring",
            "Encryption & Secrets",
        ]
        for category in categories:
            internal = _make_internal_finding(category=category)
            canonical = _convert_to_canonical(internal)
            assert canonical["kind"] in self.VALID_KINDS


# ---------------------------------------------------------------------------
# Tests: Effort values are valid canonical values
# ---------------------------------------------------------------------------

class TestEffortField:
    """Effort field must use canonical vocabulary."""

    VALID_EFFORTS = {"trivial", "low", "medium", "high"}

    def test_known_check_effort(self):
        """IAM-001 (root MFA) should have effort='low'."""
        internal = _make_internal_finding(check_id="IAM-001")
        canonical = _convert_to_canonical(internal)

        assert canonical["effort"] in self.VALID_EFFORTS
        assert canonical["effort"] == "low"

    def test_unknown_check_defaults_to_medium(self):
        """Unknown check_id defaults to effort='medium'."""
        internal = _make_internal_finding(check_id="UNKNOWN-999")
        canonical = _convert_to_canonical(internal)

        assert canonical["effort"] == "medium"

    @pytest.mark.parametrize(
        "check_id,expected_effort",
        [
            ("IAM-001", "low"),
            ("IAM-010", "trivial"),
            ("IAM-006", "high"),
            ("NET-001", "medium"),
            ("DATA-001", "trivial"),
            ("DATA-006", "high"),
            ("COMP-001", "low"),
            ("LOG-001", "low"),
            ("ENC-001", "trivial"),
        ],
    )
    def test_effort_per_check_id(self, check_id, expected_effort):
        """Each check_id maps to its documented effort level."""
        internal = _make_internal_finding(check_id=check_id)
        canonical = _convert_to_canonical(internal)

        assert canonical["effort"] == expected_effort

    def test_all_efforts_in_valid_set(self):
        """Effort from any check_id in the mapping is always a valid value."""
        from kulshan.checks.security import _EFFORT_BY_CHECK_PREFIX

        for check_id, effort in _EFFORT_BY_CHECK_PREFIX.items():
            assert effort in self.VALID_EFFORTS, (
                f"check_id {check_id} has invalid effort {effort!r}"
            )


# ---------------------------------------------------------------------------
# Tests: Full run_scan integration with mocked scanners
# ---------------------------------------------------------------------------

class TestRunScanWithMockedScanners:
    """run_scan with mocked scanners produces valid canonical output."""

    @patch("kulshan.checks.security.scanner.iam.IAMScanner")
    @patch("kulshan.checks.security.scanner.network.NetworkScanner")
    @patch("kulshan.checks.security.scanner.data.DataScanner")
    @patch("kulshan.checks.security.scanner.compute.ComputeScanner")
    @patch("kulshan.checks.security.scanner.logging_monitor.LoggingScanner")
    @patch("kulshan.checks.security.scanner.encryption.EncryptionScanner")
    @patch("kulshan.checks.security.scoring.engine.calculate_scores")
    def test_run_scan_findings_all_valid(
        self, mock_scores, mock_enc, mock_log, mock_comp, mock_data, mock_net, mock_iam
    ):
        """All findings returned by run_scan pass orchestrator validation."""
        findings = [
            _make_internal_finding(
                check_id="IAM-001",
                severity=InternalSeverity.CRITICAL,
                category="Identity & Access",
            ),
            _make_internal_finding(
                check_id="NET-001",
                severity=InternalSeverity.HIGH,
                category="Network Exposure",
            ),
        ]

        # IAM scanner produces findings, others empty
        iam_instance = MagicMock()
        iam_instance.scan.return_value = InternalScanResult(findings=findings[:1], errors=[])
        mock_iam.return_value = iam_instance

        net_instance = MagicMock()
        net_instance.scan.return_value = InternalScanResult(findings=findings[1:], errors=[])
        mock_net.return_value = net_instance

        for mock_cls in [mock_data, mock_comp, mock_log, mock_enc]:
            instance = MagicMock()
            instance.scan.return_value = InternalScanResult(findings=[], errors=[])
            mock_cls.return_value = instance

        mock_scores.return_value = {
            "overall_score": 65,
            "overall_grade": "D",
            "total_findings": 2,
            "severity_counts": {"critical": 1, "high": 1},
        }

        session = MagicMock()
        result = run_scan(session, ["us-east-1"])

        assert "findings" in result
        assert len(result["findings"]) == 2

        for finding in result["findings"]:
            is_valid, reason = validate_finding(finding)
            assert is_valid, f"Finding failed validation: {reason}"
