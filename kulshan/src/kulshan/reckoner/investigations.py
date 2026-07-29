"""Shared service-investigation descriptors for PR10."""

from __future__ import annotations

from dataclasses import dataclass

from kulshan.reckoner.contracts import QuerySpec


@dataclass(frozen=True)
class InvestigationModule:
    module_id: str
    service: str
    question: str
    query: QuerySpec
    evidence_required: tuple[str, ...] = ()
    limitations: tuple[str, ...] = ()


def built_in_investigations() -> tuple[InvestigationModule, ...]:
    from kulshan.reckoner.contracts import PeriodSpec

    return tuple(
        InvestigationModule(
            i,
            s,
            q,
            QuerySpec(
                metric="unblended-cost", period=PeriodSpec("last-30-days"), groupings=("service",)
            ),
        )
        for i, s, q in (
            ("compute-cost", "compute", "How is compute cost moving?"),
            ("storage-cost", "storage", "How is storage cost moving?"),
            ("data-transfer-cost", "data-transfer", "How is data transfer cost moving?"),
        )
    )
