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
    if dimension not in breadcrumb.query.groupings and dimension not in breadcrumb.query.groupings:
        raise ValueError(f"drilldown dimension is not in the query: {dimension}")
    return DrilldownBreadcrumb(
        breadcrumb.module_id, breadcrumb.query, breadcrumb.path + (dimension,)
    )
