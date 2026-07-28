"""Stable identifier registries for future Reckoner implementations."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from kulshan.reckoner.contracts import FilterOperator, ReckonerContractError, validate_dimension_id
from kulshan.reckoner.cost.semantics import FORMULAS, PLANNED_UNAVAILABLE


class ImplementationStatus(str, Enum):
    PLANNED = "planned"
    AVAILABLE = "available"
    UNAVAILABLE = "unavailable"
    COMPATIBILITY_ONLY = "compatibility-only"


@dataclass(frozen=True)
class MetricDescriptor:
    metric_id: str
    label: str
    description: str
    unit: str
    currency_behavior: str
    required_source_fields: tuple[str, ...]
    charge_inclusion_rules: tuple[str, ...]
    charge_exclusion_rules: tuple[str, ...]
    aggregation_behavior: str
    formula_version: str | None
    cudos_provenance: tuple[str, ...]
    focus_provenance: tuple[str, ...]
    availability_rule: str
    limitations: tuple[str, ...]
    implementation_status: ImplementationStatus


@dataclass(frozen=True)
class DimensionDescriptor:
    dimension_id: str
    label: str
    physical_expression_reference: str | None
    supported_schemas: tuple[str, ...]
    sensitivity: str
    cardinality_class: str
    required_cache_profile: str | None
    supported_operators: tuple[FilterOperator, ...]
    normalization_rule: str
    drilldowns: tuple[str, ...]
    implementation_status: ImplementationStatus


@dataclass(frozen=True)
class PeriodDescriptor:
    period_id: str
    label: str
    range_rule: str
    requires_explicit_boundaries: bool
    implementation_status: ImplementationStatus


_ALL_TEXT_OPERATORS = (
    FilterOperator.EQUALS,
    FilterOperator.NOT_EQUALS,
    FilterOperator.IN,
    FilterOperator.NOT_IN,
    FilterOperator.CONTAINS,
    FilterOperator.STARTS_WITH,
    FilterOperator.IS_NULL,
    FilterOperator.IS_NOT_NULL,
)
_ALL_COMPARABLE_OPERATORS = _ALL_TEXT_OPERATORS + (
    FilterOperator.GREATER_THAN,
    FilterOperator.LESS_THAN,
    FilterOperator.BETWEEN,
)

METRIC_IDS = (
    "invoiced-cost",
    "net-unblended-cost",
    "unblended-cost",
    "blended-cost",
    "amortized-cost",
    "net-amortized-cost",
    "effective-cost",
    "public-on-demand-cost",
    "credits",
    "refunds",
    "support",
    "taxes",
    "savings-plan-fees",
    "reserved-instance-fees",
    "unused-commitment-cost",
    "usage-quantity",
)


def _metric(metric_id: str) -> MetricDescriptor:
    label = metric_id.replace("-", " ").title()
    unit = "quantity" if metric_id == "usage-quantity" else "currency"
    return MetricDescriptor(
        metric_id=metric_id,
        label=label,
        description=f"Planned descriptor for {label}; no PR 0 formula implementation exists.",
        unit=unit,
        currency_behavior="not-applicable" if unit == "quantity" else "source-currency",
        required_source_fields=(),
        charge_inclusion_rules=(),
        charge_exclusion_rules=(),
        aggregation_behavior="planned",
        formula_version=None,
        cudos_provenance=(),
        focus_provenance=(),
        availability_rule="unavailable until a versioned formula implementation is registered",
        limitations=("Descriptor only; calculation is deliberately deferred.",),
        implementation_status=ImplementationStatus.PLANNED,
    )


METRICS = {metric_id: _metric(metric_id) for metric_id in METRIC_IDS}
METRICS["auto"] = MetricDescriptor(
    metric_id="auto",
    label="Automatic compatibility selection",
    description="Compatibility-only selector; not a metric and not a formula.",
    unit="compatibility",
    currency_behavior="selected-metric",
    required_source_fields=(),
    charge_inclusion_rules=(),
    charge_exclusion_rules=(),
    aggregation_behavior="delegates to a future explicit metric selection",
    formula_version=None,
    cudos_provenance=(),
    focus_provenance=(),
    availability_rule="compatibility-only",
    limitations=("Must resolve to an explicit metric before execution.",),
    implementation_status=ImplementationStatus.COMPATIBILITY_ONLY,
)

DIMENSION_IDS = (
    "billing-month",
    "usage-date",
    "payer",
    "account",
    "account-name",
    "service",
    "service-category",
    "region",
    "availability-zone",
    "resource",
    "usage-type",
    "operation",
    "charge-type",
    "charge-category",
    "purchase-option",
    "billing-entity",
    "legal-entity",
    "pricing-unit",
    "commitment",
    "owner",
    "application",
    "environment",
)


def _dimension(dimension_id: str) -> DimensionDescriptor:
    high_cardinality = dimension_id in {"resource", "usage-type", "operation"}
    sensitive = dimension_id in {"payer", "account", "account-name", "resource"}
    return DimensionDescriptor(
        dimension_id=dimension_id,
        label=dimension_id.replace("-", " ").title(),
        physical_expression_reference=None,
        supported_schemas=("cur-1", "cur-2", "focus"),
        sensitivity="sensitive" if sensitive else "non-sensitive",
        cardinality_class="high" if high_cardinality else "bounded",
        required_cache_profile=None,
        supported_operators=_ALL_COMPARABLE_OPERATORS,
        normalization_rule="planned; preserve source value until a versioned rule exists",
        drilldowns=(),
        implementation_status=ImplementationStatus.PLANNED,
    )


DIMENSIONS = {dimension_id: _dimension(dimension_id) for dimension_id in DIMENSION_IDS}

PERIOD_IDS = (
    "current-billing-period",
    "previous-complete-month",
    "last-7-days",
    "last-30-days",
    "last-3-complete-months",
    "last-6-complete-months",
    "last-12-complete-months",
    "last-13-billing-periods",
    "last-18-billing-periods",
    "year-to-date",
    "previous-year-to-date",
    "custom",
)

PERIODS = {
    period_id: PeriodDescriptor(
        period_id=period_id,
        label=period_id.replace("-", " ").title(),
        range_rule="start <= usage_time < end",
        requires_explicit_boundaries=period_id == "custom",
        implementation_status=ImplementationStatus.PLANNED,
    )
    for period_id in PERIOD_IDS
}


def resolve_dimension(dimension_id: str) -> DimensionDescriptor:
    """Return a static or validated dynamic descriptor."""
    validate_dimension_id(dimension_id)
    if dimension_id in DIMENSIONS:
        return DIMENSIONS[dimension_id]
    if dimension_id.startswith("tag:"):
        label = f"Tag: {dimension_id.split(':', 1)[1]}"
        sensitivity = "customer-defined"
    elif dimension_id.startswith("cost-category:"):
        label = f"Cost Category: {dimension_id.split(':', 1)[1]}"
        sensitivity = "customer-defined"
    else:
        raise ReckonerContractError(f"Unknown dimension ID: {dimension_id}")
    return DimensionDescriptor(
        dimension_id=dimension_id,
        label=label,
        physical_expression_reference=None,
        supported_schemas=("cur-1", "cur-2"),
        sensitivity=sensitivity,
        cardinality_class="customer-defined",
        required_cache_profile=None,
        supported_operators=_ALL_TEXT_OPERATORS,
        normalization_rule="key preserved exactly; value normalization deferred",
        drilldowns=(),
        implementation_status=ImplementationStatus.PLANNED,
    )


def validate_filter_operator(dimension_id: str, operator: FilterOperator) -> None:
    descriptor = resolve_dimension(dimension_id)
    if operator not in descriptor.supported_operators:
        raise ReckonerContractError(
            f"{operator.value} is not supported for dimension {dimension_id}"
        )


# PR 1 qualifies only formulas implemented by the canonical cost subsystem.

for _metric_id, _formula_definition in FORMULAS.items():
    METRICS[_metric_id] = MetricDescriptor(
        metric_id=_metric_id,
        label=_metric_id.replace("-", " ").title(),
        description=f"Canonical formula {_formula_definition.formula_id}.",
        unit="quantity" if _metric_id == "usage-quantity" else "currency",
        currency_behavior=_formula_definition.currency_behavior,
        required_source_fields=_formula_definition.required_components,
        charge_inclusion_rules=_formula_definition.charge_inclusion,
        charge_exclusion_rules=_formula_definition.charge_exclusion,
        aggregation_behavior=_formula_definition.aggregation_behavior,
        formula_version=_formula_definition.formula_version,
        cudos_provenance=_formula_definition.provenance_ids,
        focus_provenance=(),
        availability_rule="available only when source schema and required fields qualify",
        limitations=_formula_definition.limitations,
        implementation_status=ImplementationStatus.AVAILABLE,
    )

for _metric_id, _reason in PLANNED_UNAVAILABLE.items():
    _planned = METRICS[_metric_id]
    METRICS[_metric_id] = MetricDescriptor(
        **{
            **_planned.__dict__,
            "description": f"Unavailable in PR 1: {_reason}",
            "limitations": (_reason,),
            "implementation_status": ImplementationStatus.UNAVAILABLE,
        }
    )
