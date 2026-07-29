"""Deterministic guided exploration over declarative Reckoner modules."""

from __future__ import annotations

from dataclasses import dataclass

from kulshan.reckoner.contracts import QuerySpec
from kulshan.reckoner.modules import ModuleDefinition


@dataclass(frozen=True)
class DrilldownBreadcrumb:
    module_id: str
    query: QuerySpec
    path: tuple[str, ...] = ()


@dataclass(frozen=True)
class ExplorationChoice:
    module_id: str
    question: str
    description: str


def choices(modules: tuple[ModuleDefinition, ...]) -> tuple[ExplorationChoice, ...]:
    return tuple(
        ExplorationChoice(m.module_id, m.question, m.description)
        for m in sorted(modules, key=lambda item: item.module_id)
    )


def start(module: ModuleDefinition) -> DrilldownBreadcrumb:
    return DrilldownBreadcrumb(module.module_id, module.query_defaults)


def drilldown(breadcrumb: DrilldownBreadcrumb, dimension: str) -> DrilldownBreadcrumb:
    if dimension in breadcrumb.path:
        raise ValueError(f"drilldown dimension is not in the query: {dimension}")
    return DrilldownBreadcrumb(
        breadcrumb.module_id, breadcrumb.query, breadcrumb.path + (dimension,)
    )


def built_in_modules() -> tuple[ModuleDefinition, ...]:
    from kulshan.reckoner.contracts import PeriodSpec

    specs = (
        ("where-spending", "Where are we spending?", "Service-level spend overview", ("service",)),
        ("what-changed", "What changed?", "Compare recent service movement", ("service",)),
        ("movers", "Which services moved most?", "Top service movers", ("service",)),
        ("new-charges", "What charges are new?", "First-seen charge categories", ("charge-type",)),
    )
    return tuple(
        ModuleDefinition(
            schema_version="1.0",
            module_id=i,
            question=q,
            description=d,
            query_defaults=QuerySpec(
                metric="unblended-cost", period=PeriodSpec("last-30-days"), groupings=g
            ),
            allowed_overrides=("period", "groupings", "filters", "limit", "visualization"),
            output_sections=("summary", "table"),
            suggested_drilldowns=g,
            chart_preference="table",
            explanation_text=q,
            freshness_requirements=(),
            limitations=(),
            formula_provenance_references=(),
        )
        for i, q, d, g in specs
    )


def module_by_id(module_id: str) -> ModuleDefinition:
    for module in built_in_modules():
        if module.module_id == module_id:
            return module
    raise KeyError(f"unknown exploration module: {module_id}")


def export_breadcrumb(breadcrumb: DrilldownBreadcrumb) -> dict[str, object]:
    return {
        "module_id": breadcrumb.module_id,
        "path": list(breadcrumb.path),
        "query": breadcrumb.query.to_dict(),
    }
