# Feature: consistency-normalization, Property 11: v1.0 Deserialization
"""
Property-based tests for the adapter layer and v1.0 deserialization.

Property 11: v1.0 Deserialization Maps Legacy Fields

For any dict in the old models.py Finding shape (with `tool`, `check_id`,
`confidence` as enum string, `monthly_impact_usd` as Decimal string, and
no `schema_version` key), `Finding.from_dict(d)` SHALL treat it as v1.0
and produce a valid Finding with `pack` mapped from `tool`, `kind` mapped
from `check_id`, `confidence` mapped from enum to float, and
`estimated_monthly_impact` mapped from Decimal string to float.

**Validates: Requirements 6.2, 6.5**
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from hypothesis import given, settings, assume, strategies as st

from kulshan.models import (
    Finding,
    Severity,
    CONFIDENCE_ENUM_MAP,
    SEVERITY_SCORE_IMPACT,
    VALID_EFFORT,
    VALID_RISK,
)


# ---------------------------------------------------------------------------
# Strategies for generating v1.0 legacy finding dicts
# ---------------------------------------------------------------------------

# Safe text for identity fields (non-empty alphanumeric)
_identifiers = st.text(
    alphabet=st.characters(whitelist_categories=("L", "N"), max_codepoint=0x7A),
    min_size=1,
    max_size=30,
)

# Confidence enum strings (the v1.0 format)
_confidence_enum_strings = st.sampled_from(["definite", "high", "medium", "low"])

# Valid severity strings for v1.0 findings
_severity_strings = st.sampled_from(["critical", "high", "medium", "low", "info"])

# Non-negative Decimal values as strings (the v1.0 format for monthly_impact_usd)
_decimal_impact_strings = st.decimals(
    min_value=Decimal("0.00"),
    max_value=Decimal("999999.99"),
    allow_nan=False,
    allow_infinity=False,
    places=2,
).map(str)

# 16-char hex fingerprints
_fingerprints = st.from_regex(r"[0-9a-f]{16}", fullmatch=True)

# Effort values (some v1.0 findings might have effort as a valid string)
_effort_values = st.sampled_from(list(VALID_EFFORT))

# Risk values
_risk_values = st.sampled_from(list(VALID_RISK))


@st.composite
def v1_legacy_finding_dict(draw):
    """Generate a dict in the old models.py Finding shape (v1.0).

    Shape characteristics:
    - Has `tool` (str) instead of `pack`
    - Has `check_id` (str) instead of `kind`
    - Has `confidence` as enum string ("definite", "high", "medium", "low")
    - Has `monthly_impact_usd` as Decimal string instead of `estimated_monthly_impact`
    - Has NO `schema_version` key (absence indicates v1.0)
    """
    severity = draw(_severity_strings)

    d = {
        "id": draw(_identifiers),
        "tool": draw(_identifiers),
        "check_id": draw(_identifiers),
        "fingerprint": draw(_fingerprints),
        "title": draw(_identifiers),
        "severity": severity,
        "confidence": draw(_confidence_enum_strings),
        "monthly_impact_usd": draw(_decimal_impact_strings),
        "effort": draw(_effort_values),
        "risk": draw(_risk_values),
    }

    # Ensure NO schema_version key (absence indicates v1.0)
    assert "schema_version" not in d
    return d


# ---------------------------------------------------------------------------
# Property 11: v1.0 Deserialization Maps Legacy Fields
# ---------------------------------------------------------------------------


class TestV10DeserializationMapsLegacyFields:
    """
    # Feature: consistency-normalization, Property 11: v1.0 Deserialization

    For any dict in the old models.py Finding shape (with `tool`, `check_id`,
    `confidence` as enum string, `monthly_impact_usd` as Decimal string,
    and no `schema_version` key), `Finding.from_dict(d)` SHALL treat it as
    v1.0 and produce a valid Finding with:
    - `pack` mapped from `tool`
    - `kind` mapped from `check_id`
    - `confidence` mapped from enum to float (definite→1.0, high→0.85, medium→0.6, low→0.35)
    - `estimated_monthly_impact` mapped from Decimal string to float

    **Validates: Requirements 6.2, 6.5**
    """

    @settings(max_examples=100)
    @given(d=v1_legacy_finding_dict())
    def test_v1_deserialization_maps_tool_to_pack(self, d: dict):
        """Finding.from_dict(v1.0 dict) maps `tool` → `pack`."""
        original_tool = d["tool"]
        finding = Finding.from_dict(d)
        assert finding.pack == original_tool

    @settings(max_examples=100)
    @given(d=v1_legacy_finding_dict())
    def test_v1_deserialization_maps_check_id_to_kind(self, d: dict):
        """Finding.from_dict(v1.0 dict) maps `check_id` → `kind`."""
        original_check_id = d["check_id"]
        finding = Finding.from_dict(d)
        assert finding.kind == original_check_id

    @settings(max_examples=100)
    @given(d=v1_legacy_finding_dict())
    def test_v1_deserialization_maps_confidence_enum_to_float(self, d: dict):
        """Finding.from_dict(v1.0 dict) maps confidence enum string to float."""
        original_confidence_str = d["confidence"]
        expected_float = CONFIDENCE_ENUM_MAP[original_confidence_str]
        finding = Finding.from_dict(d)
        assert finding.confidence == expected_float

    @settings(max_examples=100)
    @given(d=v1_legacy_finding_dict())
    def test_v1_deserialization_maps_monthly_impact_to_float(self, d: dict):
        """Finding.from_dict(v1.0 dict) maps `monthly_impact_usd` Decimal string to float."""
        original_impact_str = d["monthly_impact_usd"]
        expected_float = float(Decimal(original_impact_str))
        finding = Finding.from_dict(d)
        assert abs(finding.estimated_monthly_impact - expected_float) < 0.01

    @settings(max_examples=100)
    @given(d=v1_legacy_finding_dict())
    def test_v1_deserialization_produces_valid_finding(self, d: dict):
        """Finding.from_dict(v1.0 dict) produces a valid Finding instance."""
        finding = Finding.from_dict(d)

        # The result is a Finding instance
        assert isinstance(finding, Finding)

        # Severity is a valid Severity enum member
        assert isinstance(finding.severity, Severity)

        # Confidence is in [0.0, 1.0]
        assert 0.0 <= finding.confidence <= 1.0

        # Effort is in valid set
        assert finding.effort in VALID_EFFORT

        # Risk is in valid set
        assert finding.risk in VALID_RISK

        # score_impact matches severity
        assert finding.score_impact == SEVERITY_SCORE_IMPACT[finding.severity.value]

        # Schema version is set to "2.0" after parsing
        assert finding.schema_version == "2.0"

    @settings(max_examples=100)
    @given(d=v1_legacy_finding_dict())
    def test_v1_deserialization_absence_of_schema_version_means_v1(self, d: dict):
        """A dict without `schema_version` is treated as v1.0."""
        # Confirm no schema_version key in input
        assert "schema_version" not in d

        # from_dict should still succeed (treats as v1.0)
        finding = Finding.from_dict(d)

        # The resulting finding should have schema_version "2.0" (canonical)
        assert finding.schema_version == "2.0"
