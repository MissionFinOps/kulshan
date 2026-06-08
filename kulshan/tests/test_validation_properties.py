# Feature: consistency-normalization, Property 7: Validation Accepts Valid, Rejects Invalid
"""
Property-based tests for orchestrator validate_finding().

Property 7: Validation Accepts Valid, Rejects Invalid

For any dict, validate_finding(d) SHALL return (True, "") if and only if the dict
contains all required keys (id, pack, kind, title, severity, confidence, effort, risk)
as non-empty strings of ≤512 characters, with severity in the canonical set,
confidence a float in [0.0, 1.0], effort in the canonical set, and risk in the
canonical set. Otherwise it SHALL return (False, reason).

**Validates: Requirements 7.3, 7.4, 7.5, 7.6**
"""

from __future__ import annotations

import pytest
from hypothesis import given, settings, assume, strategies as st

from kulshan.orchestrator import validate_finding
from kulshan.models import VALID_SEVERITY, VALID_EFFORT, VALID_RISK


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

# Non-empty strings ≤512 chars for required string fields
_valid_strings = st.text(
    alphabet=st.characters(whitelist_categories=("L", "N", "P"), max_codepoint=0x7E),
    min_size=1,
    max_size=100,
)

# Valid severity values
_valid_severity = st.sampled_from(list(VALID_SEVERITY))

# Valid confidence: float in [0.0, 1.0]
_valid_confidence = st.floats(
    min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False
)

# Valid effort values
_valid_effort = st.sampled_from(list(VALID_EFFORT))

# Valid risk values
_valid_risk = st.sampled_from(list(VALID_RISK))


@st.composite
def valid_finding_dict(draw):
    """Generate a dict that should pass validate_finding with (True, "")."""
    return {
        "id": draw(_valid_strings),
        "pack": draw(_valid_strings),
        "kind": draw(_valid_strings),
        "title": draw(_valid_strings),
        "severity": draw(_valid_severity),
        "confidence": draw(_valid_confidence),
        "effort": draw(_valid_effort),
        "risk": draw(_valid_risk),
    }


# ---------------------------------------------------------------------------
# Strategies for invalid findings
# ---------------------------------------------------------------------------

# Required keys for validation
_REQUIRED_KEYS = ("id", "pack", "kind", "title", "severity", "confidence", "effort", "risk")

# String fields that must be non-empty and ≤512 chars
_REQUIRED_STRING_KEYS = ("id", "pack", "kind", "title")


@st.composite
def finding_dict_missing_keys(draw):
    """Generate a finding dict missing one or more required keys."""
    base = draw(valid_finding_dict())
    keys_to_remove = draw(
        st.lists(
            st.sampled_from(list(_REQUIRED_KEYS)),
            min_size=1,
            max_size=len(_REQUIRED_KEYS),
            unique=True,
        )
    )
    for key in keys_to_remove:
        base.pop(key, None)
    return base


@st.composite
def finding_dict_with_empty_string_field(draw):
    """Generate a finding dict where one required string field is empty."""
    base = draw(valid_finding_dict())
    field_to_empty = draw(st.sampled_from(list(_REQUIRED_STRING_KEYS)))
    base[field_to_empty] = ""
    return base


@st.composite
def finding_dict_with_overlong_string(draw):
    """Generate a finding dict where one required string field exceeds 512 chars."""
    base = draw(valid_finding_dict())
    field_to_overflow = draw(st.sampled_from(list(_REQUIRED_STRING_KEYS)))
    # Generate a string that is 513-600 chars long
    long_str = draw(st.text(
        alphabet=st.characters(whitelist_categories=("L",), max_codepoint=0x7A),
        min_size=513,
        max_size=600,
    ))
    base[field_to_overflow] = long_str
    return base


# Invalid severity: string not in the canonical set
_invalid_severity = st.text(
    alphabet=st.characters(whitelist_categories=("L", "N"), max_codepoint=0x7A),
    min_size=1,
    max_size=20,
).filter(lambda s: s not in VALID_SEVERITY)


# Invalid confidence: floats outside [0.0, 1.0]
_invalid_confidence = st.one_of(
    st.floats(max_value=-0.001, allow_nan=False, allow_infinity=False),
    st.floats(min_value=1.001, max_value=1e10, allow_nan=False, allow_infinity=False),
)

# Invalid effort: string not in VALID_EFFORT
_invalid_effort = st.text(
    alphabet=st.characters(whitelist_categories=("L", "N"), max_codepoint=0x7A),
    min_size=1,
    max_size=20,
).filter(lambda s: s not in VALID_EFFORT)

# Invalid risk: string not in VALID_RISK
_invalid_risk = st.text(
    alphabet=st.characters(whitelist_categories=("L", "N"), max_codepoint=0x7A),
    min_size=1,
    max_size=20,
).filter(lambda s: s not in VALID_RISK)


@st.composite
def finding_dict_with_invalid_severity(draw):
    """Generate a finding dict with an invalid severity value."""
    base = draw(valid_finding_dict())
    base["severity"] = draw(_invalid_severity)
    return base


@st.composite
def finding_dict_with_invalid_confidence(draw):
    """Generate a finding dict with confidence outside [0.0, 1.0]."""
    base = draw(valid_finding_dict())
    base["confidence"] = draw(_invalid_confidence)
    return base


@st.composite
def finding_dict_with_invalid_effort(draw):
    """Generate a finding dict with an invalid effort value."""
    base = draw(valid_finding_dict())
    base["effort"] = draw(_invalid_effort)
    return base


@st.composite
def finding_dict_with_invalid_risk(draw):
    """Generate a finding dict with an invalid risk value."""
    base = draw(valid_finding_dict())
    base["risk"] = draw(_invalid_risk)
    return base


# Non-dict values to test type rejection
_non_dict_values = st.one_of(
    st.none(),
    st.integers(),
    st.text(min_size=0, max_size=50),
    st.lists(st.integers(), max_size=5),
    st.just(42.0),
    st.just(True),
)


# ---------------------------------------------------------------------------
# Property Tests: Valid dicts → (True, "")
# ---------------------------------------------------------------------------

class TestValidationAcceptsValid:
    """
    # Feature: consistency-normalization, Property 7: Validation Accepts Valid, Rejects Invalid

    Valid finding dicts (all required keys present, correct types/ranges)
    must return (True, "").

    **Validates: Requirements 7.3, 7.4, 7.5, 7.6**
    """

    @settings(max_examples=100)
    @given(d=valid_finding_dict())
    def test_valid_finding_returns_true(self, d: dict):
        """validate_finding(d) returns (True, "") for any valid finding dict."""
        result = validate_finding(d)
        assert result == (True, ""), f"Expected (True, '') but got {result} for {d}"


# ---------------------------------------------------------------------------
# Property Tests: Invalid dicts → (False, reason)
# ---------------------------------------------------------------------------

class TestValidationRejectsInvalid:
    """
    # Feature: consistency-normalization, Property 7: Validation Accepts Valid, Rejects Invalid

    Invalid finding dicts (missing keys, out-of-range values, empty strings,
    non-dict, strings over 512 chars) must return (False, reason).

    **Validates: Requirements 7.3, 7.4, 7.5, 7.6**
    """

    @settings(max_examples=100)
    @given(d=finding_dict_missing_keys())
    def test_missing_keys_returns_false(self, d: dict):
        """validate_finding rejects dicts with missing required keys."""
        is_valid, reason = validate_finding(d)
        assert is_valid is False
        assert reason != ""

    @settings(max_examples=100)
    @given(d=finding_dict_with_empty_string_field())
    def test_empty_string_field_returns_false(self, d: dict):
        """validate_finding rejects dicts with empty required string fields."""
        is_valid, reason = validate_finding(d)
        assert is_valid is False
        assert reason != ""

    @settings(max_examples=100)
    @given(d=finding_dict_with_overlong_string())
    def test_overlong_string_returns_false(self, d: dict):
        """validate_finding rejects dicts with string fields exceeding 512 chars."""
        is_valid, reason = validate_finding(d)
        assert is_valid is False
        assert reason != ""

    @settings(max_examples=100)
    @given(value=_non_dict_values)
    def test_non_dict_returns_false(self, value):
        """validate_finding rejects non-dict inputs."""
        is_valid, reason = validate_finding(value)
        assert is_valid is False
        assert reason != ""

    @settings(max_examples=100)
    @given(d=finding_dict_with_invalid_severity())
    def test_invalid_severity_returns_false(self, d: dict):
        """validate_finding rejects dicts with invalid severity values."""
        is_valid, reason = validate_finding(d)
        assert is_valid is False
        assert reason != ""

    @settings(max_examples=100)
    @given(d=finding_dict_with_invalid_confidence())
    def test_invalid_confidence_returns_false(self, d: dict):
        """validate_finding rejects dicts with confidence outside [0.0, 1.0]."""
        is_valid, reason = validate_finding(d)
        assert is_valid is False
        assert reason != ""

    @settings(max_examples=100)
    @given(d=finding_dict_with_invalid_effort())
    def test_invalid_effort_returns_false(self, d: dict):
        """validate_finding rejects dicts with invalid effort values."""
        is_valid, reason = validate_finding(d)
        assert is_valid is False
        assert reason != ""

    @settings(max_examples=100)
    @given(d=finding_dict_with_invalid_risk())
    def test_invalid_risk_returns_false(self, d: dict):
        """validate_finding rejects dicts with invalid risk values."""
        is_valid, reason = validate_finding(d)
        assert is_valid is False
        assert reason != ""
