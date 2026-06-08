# Feature: consistency-normalization, Property 1: Serialization Round-Trip
# Feature: consistency-normalization, Property 2: Constraint Enforcement
"""
Property-based tests for canonical Finding dataclass.

Property 1: Serialization Round-Trip
For any valid Finding instance (with arbitrary field values including
timezone-aware datetimes, non-empty evidence dicts, and varying optional
fields), Finding.from_dict(json.loads(json.dumps(f.to_dict()))) SHALL
produce a Finding whose every field is equal to the original instance.

**Validates: Requirements 1.14, 8.1, 8.2, 8.3, 8.4, 6.3**

Property 2: Constraint Enforcement on Construction
For any combination of field values where at least one of: severity is not in
{critical, high, medium, low, info}, confidence is outside [0.0, 1.0], effort
is not in {trivial, low, medium, high}, or risk is not in {safe, low, medium, high},
constructing a Finding (directly or via from_dict) SHALL raise a ValueError.

**Validates: Requirements 1.15, 1.17**
"""

from __future__ import annotations

import json
from datetime import datetime, timezone, timedelta

import pytest
from hypothesis import given, settings, assume, strategies as st

from kulshan.models import (
    Finding,
    Severity,
    SEVERITY_SCORE_IMPACT,
    VALID_EFFORT,
    VALID_RISK,
)


# ---------------------------------------------------------------------------
# Strategies for generating INVALID field values
# ---------------------------------------------------------------------------

# Valid values (used when we need other fields to be correct)
valid_severities = st.sampled_from(list(Severity))
valid_confidence = st.floats(min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False)
valid_effort = st.sampled_from(list(VALID_EFFORT))
valid_risk = st.sampled_from(list(VALID_RISK))

# Invalid severity strings: anything that is NOT a valid Severity enum value
invalid_severity_strings = st.text(
    alphabet=st.characters(whitelist_categories=("L", "N"), max_codepoint=0x7A),
    min_size=1,
    max_size=20,
).filter(lambda s: s.lower() not in ("critical", "high", "medium", "low", "info"))

# Invalid confidence: floats outside [0.0, 1.0]
invalid_confidence = st.one_of(
    st.floats(max_value=-0.001, allow_nan=False, allow_infinity=False),
    st.floats(min_value=1.001, allow_nan=False, allow_infinity=False, max_value=1e10),
)

# Invalid effort strings: anything NOT in VALID_EFFORT
invalid_effort = st.text(
    alphabet=st.characters(whitelist_categories=("L", "N"), max_codepoint=0x7A),
    min_size=1,
    max_size=20,
).filter(lambda s: s not in VALID_EFFORT)

# Invalid risk strings: anything NOT in VALID_RISK
invalid_risk = st.text(
    alphabet=st.characters(whitelist_categories=("L", "N"), max_codepoint=0x7A),
    min_size=1,
    max_size=20,
).filter(lambda s: s not in VALID_RISK)

# Safe text for identity fields
identifiers = st.text(
    alphabet=st.characters(whitelist_categories=("L", "N"), max_codepoint=0x7A),
    min_size=1,
    max_size=30,
)


# ---------------------------------------------------------------------------
# Helper: build a valid base dict for from_dict testing
# ---------------------------------------------------------------------------

def _make_valid_finding_dict(
    severity: str = "high",
    confidence: float = 0.85,
    effort: str = "medium",
    risk: str = "safe",
) -> dict:
    """Build a minimal valid finding dict (schema 2.0) for from_dict."""
    return {
        "id": "test-finding-001",
        "pack": "cost",
        "kind": "anomaly_statistical",
        "fingerprint": "a1b2c3d4e5f6g7h8",
        "title": "Test finding",
        "severity": severity,
        "score_impact": SEVERITY_SCORE_IMPACT[severity],
        "estimated_monthly_impact": 100.0,
        "confidence": confidence,
        "effort": effort,
        "risk": risk,
        "schema_version": "2.0",
    }


# ---------------------------------------------------------------------------
# Property Tests
# ---------------------------------------------------------------------------

class TestConstraintEnforcementDirect:
    """Property 2: Direct construction with invalid field values raises ValueError.

    # Feature: consistency-normalization, Property 2: Constraint Enforcement
    **Validates: Requirements 1.15, 1.17**
    """

    @settings(max_examples=100)
    @given(bad_severity=invalid_severity_strings)
    def test_invalid_severity_raises_valueerror(self, bad_severity: str):
        """Constructing Finding with non-enum severity raises ValueError."""
        with pytest.raises((ValueError, KeyError)):
            Finding(
                id="test-id",
                pack="cost",
                kind="anomaly",
                fingerprint="abcdef1234567890",
                title="Test",
                severity=bad_severity,  # type: ignore
                score_impact=-10,
                estimated_monthly_impact=100.0,
                confidence=0.85,
                effort="medium",
                risk="safe",
            )

    @settings(max_examples=100)
    @given(bad_confidence=invalid_confidence)
    def test_invalid_confidence_raises_valueerror(self, bad_confidence: float):
        """Constructing Finding with confidence outside [0.0, 1.0] raises ValueError."""
        with pytest.raises(ValueError):
            Finding(
                id="test-id",
                pack="cost",
                kind="anomaly",
                fingerprint="abcdef1234567890",
                title="Test",
                severity=Severity.HIGH,
                score_impact=-10,
                estimated_monthly_impact=100.0,
                confidence=bad_confidence,
                effort="medium",
                risk="safe",
            )

    @settings(max_examples=100)
    @given(bad_effort=invalid_effort)
    def test_invalid_effort_raises_valueerror(self, bad_effort: str):
        """Constructing Finding with effort not in valid set raises ValueError."""
        with pytest.raises(ValueError):
            Finding(
                id="test-id",
                pack="cost",
                kind="anomaly",
                fingerprint="abcdef1234567890",
                title="Test",
                severity=Severity.HIGH,
                score_impact=-10,
                estimated_monthly_impact=100.0,
                confidence=0.85,
                effort=bad_effort,
                risk="safe",
            )

    @settings(max_examples=100)
    @given(bad_risk=invalid_risk)
    def test_invalid_risk_raises_valueerror(self, bad_risk: str):
        """Constructing Finding with risk not in valid set raises ValueError."""
        with pytest.raises(ValueError):
            Finding(
                id="test-id",
                pack="cost",
                kind="anomaly",
                fingerprint="abcdef1234567890",
                title="Test",
                severity=Severity.HIGH,
                score_impact=-10,
                estimated_monthly_impact=100.0,
                confidence=0.85,
                effort="medium",
                risk=bad_risk,
            )


class TestConstraintEnforcementFromDict:
    """Property 2: from_dict with invalid field values raises ValueError.

    # Feature: consistency-normalization, Property 2: Constraint Enforcement
    **Validates: Requirements 1.15, 1.17**
    """

    @settings(max_examples=100)
    @given(bad_severity=invalid_severity_strings)
    def test_from_dict_invalid_severity_raises_valueerror(self, bad_severity: str):
        """from_dict with invalid severity value raises ValueError."""
        d = _make_valid_finding_dict()
        d["severity"] = bad_severity
        with pytest.raises(ValueError):
            Finding.from_dict(d)

    @settings(max_examples=100)
    @given(bad_confidence=invalid_confidence)
    def test_from_dict_invalid_confidence_raises_valueerror(self, bad_confidence: float):
        """from_dict with confidence outside [0.0, 1.0] raises ValueError."""
        d = _make_valid_finding_dict()
        d["confidence"] = bad_confidence
        with pytest.raises(ValueError):
            Finding.from_dict(d)

    @settings(max_examples=100)
    @given(bad_effort=invalid_effort)
    def test_from_dict_invalid_effort_raises_valueerror(self, bad_effort: str):
        """from_dict with effort not in valid set raises ValueError."""
        d = _make_valid_finding_dict()
        d["effort"] = bad_effort
        with pytest.raises(ValueError):
            Finding.from_dict(d)

    @settings(max_examples=100)
    @given(bad_risk=invalid_risk)
    def test_from_dict_invalid_risk_raises_valueerror(self, bad_risk: str):
        """from_dict with risk not in valid set raises ValueError."""
        d = _make_valid_finding_dict()
        d["risk"] = bad_risk
        with pytest.raises(ValueError):
            Finding.from_dict(d)


# ---------------------------------------------------------------------------
# Property 1: Serialization Round-Trip
# ---------------------------------------------------------------------------

# Timezone-aware datetimes within a reasonable range (varying offsets)
_tz_offsets = st.integers(min_value=-12, max_value=14).map(
    lambda h: timezone(timedelta(hours=h))
)
_aware_datetimes = st.datetimes(
    min_value=datetime(2020, 1, 1),
    max_value=datetime(2030, 12, 31),
    timezones=_tz_offsets,
)

# 16-char hex fingerprints
_fingerprints = st.from_regex(r"[0-9a-f]{16}", fullmatch=True)

# Estimated monthly impact: non-negative float
_monthly_impacts = st.floats(
    min_value=0.0, max_value=999_999_999.99, allow_nan=False, allow_infinity=False
)

# JSON-serializable evidence dict values
_json_primitives = st.one_of(
    st.none(),
    st.booleans(),
    st.integers(min_value=-1000, max_value=1000),
    st.floats(min_value=-1e6, max_value=1e6, allow_nan=False, allow_infinity=False),
    identifiers,
)

_evidence_dicts = st.dictionaries(
    keys=identifiers,
    values=_json_primitives,
    min_size=0,
    max_size=5,
)

# Compliance framework lists
_compliance_lists = st.lists(identifiers, min_size=0, max_size=4)

# Optional string fields
_optional_strings = st.one_of(st.none(), identifiers)

# AWS regions
_regions = st.sampled_from([
    "us-east-1", "us-west-2", "eu-west-1", "ap-southeast-1",
    "ca-central-1", "eu-central-1",
])


@st.composite
def valid_finding_strategy(draw):
    """Generate an arbitrary valid canonical Finding instance.

    All constraints are satisfied:
    - severity is a Severity enum member
    - confidence is in [0.0, 1.0]
    - effort is in VALID_EFFORT
    - risk is in VALID_RISK
    - score_impact matches SEVERITY_SCORE_IMPACT[severity.value]
    - evidence is JSON-serializable
    - detected_at is timezone-aware if present
    """
    severity = draw(valid_severities)
    score_impact = SEVERITY_SCORE_IMPACT[severity.value]

    return Finding(
        id=draw(identifiers),
        pack=draw(identifiers),
        kind=draw(identifiers),
        fingerprint=draw(_fingerprints),
        title=draw(identifiers),
        severity=severity,
        score_impact=score_impact,
        estimated_monthly_impact=draw(_monthly_impacts),
        confidence=draw(valid_confidence),
        effort=draw(valid_effort),
        risk=draw(valid_risk),
        account_id=draw(_optional_strings),
        region=draw(st.one_of(st.none(), _regions)),
        resource_arn=draw(_optional_strings),
        resource_type=draw(_optional_strings),
        service=draw(_optional_strings),
        description=draw(st.one_of(st.just(""), identifiers)),
        evidence=draw(_evidence_dicts),
        recommended_action=draw(st.one_of(st.just(""), identifiers)),
        compliance_frameworks=draw(_compliance_lists),
        detected_at=draw(st.one_of(st.none(), _aware_datetimes)),
        schema_version="2.0",
    )


class TestFindingSerializationRoundTrip:
    """
    Feature: consistency-normalization, Property 1: Serialization Round-Trip

    **Validates: Requirements 1.14, 8.1, 8.2, 8.3, 8.4, 6.3**

    For any valid Finding instance, serializing to dict, then to JSON string,
    then back to dict, then reconstructing via from_dict produces an equal
    Finding.
    """

    @settings(max_examples=100)
    @given(finding=valid_finding_strategy())
    def test_roundtrip_through_json(self, finding: Finding):
        """Finding.from_dict(json.loads(json.dumps(f.to_dict()))) == f"""
        serialized = finding.to_dict()
        json_str = json.dumps(serialized)
        deserialized_dict = json.loads(json_str)
        restored = Finding.from_dict(deserialized_dict)

        # Identity fields
        assert restored.id == finding.id
        assert restored.pack == finding.pack
        assert restored.kind == finding.kind
        assert restored.fingerprint == finding.fingerprint

        # Severity & impact
        assert restored.title == finding.title
        assert restored.severity == finding.severity
        assert restored.score_impact == finding.score_impact
        assert restored.estimated_monthly_impact == finding.estimated_monthly_impact
        assert restored.confidence == finding.confidence
        assert restored.effort == finding.effort
        assert restored.risk == finding.risk

        # Location (optional fields)
        assert restored.account_id == finding.account_id
        assert restored.region == finding.region
        assert restored.resource_arn == finding.resource_arn
        assert restored.resource_type == finding.resource_type
        assert restored.service == finding.service

        # Explanation
        assert restored.description == finding.description
        assert restored.evidence == finding.evidence
        assert restored.recommended_action == finding.recommended_action

        # Metadata
        assert restored.compliance_frameworks == finding.compliance_frameworks
        assert restored.detected_at == finding.detected_at
        assert restored.schema_version == finding.schema_version

        # Full equality check
        assert restored == finding


# ---------------------------------------------------------------------------
# Property 3: Missing Required Fields Rejection
# ---------------------------------------------------------------------------

# Required keys as defined by the design document
REQUIRED_KEYS = (
    "id", "pack", "kind", "fingerprint", "title", "severity",
    "score_impact", "estimated_monthly_impact", "confidence",
    "effort", "risk",
)


@st.composite
def complete_valid_finding_dict(draw):
    """Generate a fully-valid canonical finding dict (schema v2.0) for subtraction."""
    severity = draw(st.sampled_from(["critical", "high", "medium", "low", "info"]))
    score_impact = SEVERITY_SCORE_IMPACT[severity]
    effort = draw(st.sampled_from(list(VALID_EFFORT)))
    risk = draw(st.sampled_from(list(VALID_RISK)))
    confidence = draw(valid_confidence)

    return {
        "id": draw(identifiers),
        "pack": draw(identifiers),
        "kind": draw(identifiers),
        "fingerprint": draw(_fingerprints),
        "title": draw(identifiers),
        "severity": severity,
        "score_impact": score_impact,
        "estimated_monthly_impact": draw(st.floats(
            min_value=0.0, max_value=999999.99,
            allow_nan=False, allow_infinity=False,
        )),
        "confidence": confidence,
        "effort": effort,
        "risk": risk,
        "schema_version": "2.0",
    }


@st.composite
def finding_dict_missing_required_keys(draw):
    """Generate a dict that is missing one or more required keys.

    Starts from a valid finding dict and removes a non-empty subset
    of the required keys.
    """
    base = draw(complete_valid_finding_dict())

    # Choose a non-empty subset of required keys to remove
    keys_to_remove = draw(
        st.lists(
            st.sampled_from(list(REQUIRED_KEYS)),
            min_size=1,
            max_size=len(REQUIRED_KEYS),
            unique=True,
        )
    )

    for key in keys_to_remove:
        base.pop(key, None)

    return base


class TestMissingRequiredFieldsRejection:
    """
    # Feature: consistency-normalization, Property 3: Missing Required Fields

    Property 3: Missing Required Fields Rejection

    For any dictionary that is missing one or more of the required keys
    (id, pack, kind, fingerprint, title, severity, score_impact,
    estimated_monthly_impact, confidence, effort, risk),
    calling Finding.from_dict(d) SHALL raise a KeyError.

    **Validates: Requirements 1.16**
    """

    @settings(max_examples=100)
    @given(d=finding_dict_missing_required_keys())
    def test_missing_required_fields_raises_key_error(self, d: dict):
        """Finding.from_dict(d) raises KeyError when required keys are missing."""
        with pytest.raises(KeyError):
            Finding.from_dict(d)
