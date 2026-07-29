"""Qualified commitment and allocation metadata for PR9."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class ClaimClass(StrEnum):
    OBSERVED_COST = "observed-cost"
    ESTIMATED_OPPORTUNITY = "estimated-opportunity"
    VALIDATED_SAVING = "validated-saving"
    INSUFFICIENT_EVIDENCE = "insufficient-evidence"


@dataclass(frozen=True)
class CommitmentProfile:
    commitment_type: str
    coverage_ratio: float | None
    utilization_ratio: float | None
    fee_cost: float | None
    unused_cost: float | None
    source_schema: str
    limitations: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.commitment_type not in {"savings-plan", "reserved-instance", "unknown"}:
            raise ValueError("unsupported commitment type")
        for value in (self.coverage_ratio, self.utilization_ratio):
            if value is not None and not 0 <= value <= 1:
                raise ValueError("commitment ratios must be between 0 and 1")


def claim_class(
    *,
    has_observed_cost: bool,
    has_qualified_opportunity: bool = False,
    has_validated_saving: bool = False,
) -> ClaimClass:
    if has_validated_saving:
        return ClaimClass.VALIDATED_SAVING
    if has_qualified_opportunity:
        return ClaimClass.ESTIMATED_OPPORTUNITY
    if has_observed_cost:
        return ClaimClass.OBSERVED_COST
    return ClaimClass.INSUFFICIENT_EVIDENCE
