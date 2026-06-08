# Feature: consistency-normalization, Property 9: top_n Deterministic Sort
"""
Property-based tests for findings_ranker.top_n deterministic sort order.

Property 9: top_n Deterministic Sort Order

For any list of valid finding dicts and any positive integer n,
top_n(findings, n) SHALL return a list of length <= n where each element's
composite priority is >= the next element's priority, and repeated calls
with identical input produce identical output order (deterministic tie-break
on impact desc then id asc).

**Validates: Requirements 5.4**
"""

from __future__ import annotations

from hypothesis import given, settings, strategies as st

from kulshan.findings_ranker import top_n, priority
from kulshan.models import SEVERITY_SCORE_IMPACT, VALID_EFFORT, VALID_RISK


# ---------------------------------------------------------------------------
# Strategies for generating valid finding dicts
# ---------------------------------------------------------------------------

# Safe identifiers for string fields
_identifiers = st.text(
    alphabet=st.characters(whitelist_categories=("L", "N"), max_codepoint=0x7A),
    min_size=1,
    max_size=30,
)

# 16-char hex fingerprints
_fingerprints = st.from_regex(r"[0-9a-f]{16}", fullmatch=True)

# Valid canonical field values
_severities = st.sampled_from(["critical", "high", "medium", "low", "info"])
_confidences = st.floats(min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False)
_efforts = st.sampled_from(list(VALID_EFFORT))
_risks = st.sampled_from(list(VALID_RISK))
_impacts = st.floats(min_value=0.0, max_value=999_999.0, allow_nan=False, allow_infinity=False)


@st.composite
def valid_finding_dict(draw):
    """Generate a valid canonical finding dict suitable for the ranker."""
    severity = draw(_severities)
    score_impact = SEVERITY_SCORE_IMPACT[severity]

    return {
        "id": draw(_identifiers),
        "pack": draw(_identifiers),
        "kind": draw(_identifiers),
        "fingerprint": draw(_fingerprints),
        "title": draw(_identifiers),
        "severity": severity,
        "score_impact": score_impact,
        "estimated_monthly_impact": draw(_impacts),
        "confidence": draw(_confidences),
        "effort": draw(_efforts),
        "risk": draw(_risks),
        "schema_version": "2.0",
    }


# Lists of valid finding dicts (0 to 20 items)
_finding_lists = st.lists(valid_finding_dict(), min_size=0, max_size=20)

# Positive integer n for top_n
_positive_n = st.integers(min_value=1, max_value=50)


# ---------------------------------------------------------------------------
# Property 9: top_n Deterministic Sort Order
# ---------------------------------------------------------------------------

class TestTopNDeterministicSort:
    """
    # Feature: consistency-normalization, Property 9: top_n Deterministic Sort

    **Validates: Requirements 5.4**
    """

    @settings(max_examples=100)
    @given(findings=_finding_lists, n=_positive_n)
    def test_result_length_at_most_n(self, findings: list, n: int):
        """top_n(findings, n) returns a list of length <= n."""
        result = top_n(findings, n)
        assert len(result) <= n

    @settings(max_examples=100)
    @given(findings=_finding_lists, n=_positive_n)
    def test_result_length_at_most_input_length(self, findings: list, n: int):
        """top_n(findings, n) returns at most len(findings) elements."""
        result = top_n(findings, n)
        assert len(result) <= len(findings)

    @settings(max_examples=100)
    @given(findings=_finding_lists, n=_positive_n)
    def test_priority_non_increasing(self, findings: list, n: int):
        """Each element's priority >= the next element's priority (sorted desc)."""
        result = top_n(findings, n)
        for i in range(len(result) - 1):
            p_current = priority(result[i])
            p_next = priority(result[i + 1])
            assert p_current >= p_next, (
                f"Priority not non-increasing at index {i}: "
                f"{p_current} < {p_next}"
            )

    @settings(max_examples=100)
    @given(findings=_finding_lists, n=_positive_n)
    def test_repeated_calls_identical_order(self, findings: list, n: int):
        """Repeated calls with identical input produce identical output order."""
        result1 = top_n(findings, n)
        result2 = top_n(findings, n)
        # Same length
        assert len(result1) == len(result2)
        # Same order element by element
        for i, (a, b) in enumerate(zip(result1, result2)):
            assert a == b, (
                f"Different element at index {i} on repeated call: "
                f"{a} != {b}"
            )
