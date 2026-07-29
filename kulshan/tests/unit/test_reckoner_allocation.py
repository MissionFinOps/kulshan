import pytest
from kulshan.reckoner.allocation import ClaimClass, CommitmentProfile, claim_class


def test_commitment_profile_and_claim_classes_are_qualified():
    profile = CommitmentProfile("savings-plan", 0.8, 0.75, 10.0, 2.0, "legacy-cur")
    assert profile.coverage_ratio == 0.8
    assert claim_class(has_observed_cost=True) is ClaimClass.OBSERVED_COST
    assert (
        claim_class(has_observed_cost=True, has_qualified_opportunity=True)
        is ClaimClass.ESTIMATED_OPPORTUNITY
    )
    assert claim_class(has_observed_cost=False) is ClaimClass.INSUFFICIENT_EVIDENCE


def test_commitment_ratios_are_bounded():
    with pytest.raises(ValueError):
        CommitmentProfile("reserved-instance", 1.2, None, None, None, "legacy-cur")
