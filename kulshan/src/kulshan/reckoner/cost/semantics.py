"""Canonical, versioned AWS cost semantics for DuckDB relations.

This module is deliberately renderer- and source-location-neutral.  Adapters
project supported billing schemas into one relation; metrics are then evaluated
against that relation without local/S3-specific formula implementations.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from enum import Enum
from typing import Any

from .errors import (
    AmbiguousSchemaError,
    IncompatibleColumnTypeError,
    InvalidGroupingError,
    MetricUnavailableError,
    MissingCurrencyError,
    MissingRequiredFieldsError,
    MixedCurrencyError,
    UnsupportedSchemaError,
    UnsupportedSourceVersionError,
)

RELATION_VERSION = "1.0"
CLASSIFICATION_VERSION = "1.0"
FORMULA_VERSION = "1.0"


class SourceSchemaType(str, Enum):
    LEGACY_CUR = "aws-cur-legacy"
    CUR_2 = "aws-cur-2.0"
    FOCUS_1_0_AWS = "aws-focus-1.0"


class ChargeCategory(str, Enum):
    USAGE = "usage"
    RECURRING_COMMITMENT_FEE = "recurring-commitment-fee"
    UPFRONT_COMMITMENT_FEE = "upfront-commitment-fee"
    SAVINGS_PLAN_COVERED_USAGE = "savings-plan-covered-usage"
    RESERVED_INSTANCE_DISCOUNTED_USAGE = "reserved-instance-discounted-usage"
    UNUSED_COMMITMENT = "unused-commitment"
    CREDIT = "credit"
    REFUND = "refund"
    TAX = "tax"
    SUPPORT = "support"
    MARKETPLACE = "marketplace"
    DISCOUNT = "discount"
    FEE = "fee"
    ADJUSTMENT = "adjustment"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class SourceSchema:
    source_type: SourceSchemaType
    source_version: str
    supported_fields: tuple[str, ...]
    missing_required_fields: tuple[str, ...] = ()
    optional_fields: tuple[str, ...] = ()
    available_metrics: tuple[str, ...] = ()


@dataclass(frozen=True)
class ParquetSource:
    locations: tuple[str, ...]
    source_kind: str = "local"
    manifest_id: str | None = None
    region: str | None = None

    def __post_init__(self) -> None:
        if self.source_kind not in {"local", "s3"}:
            raise ValueError("source_kind must be 'local' or 's3'")
        if not self.locations:
            raise ValueError("at least one explicit Parquet location is required")
        if self.source_kind == "s3" and not self.manifest_id:
            raise ValueError("S3 sources require a pinned manifest identifier")
        if any("*" in item or "?" in item for item in self.locations):
            raise ValueError("recursive or wildcard Parquet locations are not allowed")


@dataclass(frozen=True)
class CanonicalRelation:
    relation_name: str
    source: SourceSchema
    source_kind: str
    relation_version: str = RELATION_VERSION


@dataclass(frozen=True)
class CostFormula:
    metric_id: str
    formula_id: str
    formula_version: str
    expression: str
    required_components: tuple[str, ...]
    supported_schemas: tuple[SourceSchemaType, ...]
    charge_inclusion: tuple[str, ...]
    charge_exclusion: tuple[str, ...]
    null_behavior: str
    currency_behavior: str
    aggregation_behavior: str
    provenance_ids: tuple[str, ...]
    limitations: tuple[str, ...] = ()


@dataclass(frozen=True)
class AutoSelection:
    selected_metric: str
    fallback_order: tuple[str, ...]
    missing_preferred_fields: Mapping[str, tuple[str, ...]]
    fallback_reason: str


@dataclass(frozen=True)
class CostMetricResult:
    metric_id: str
    formula_id: str
    formula_version: str
    currency: str | None
    rows: tuple[Mapping[str, Any], ...]
    total: float
    source_schema: str
    source_version: str
    limitations: tuple[str, ...]
    auto_selection: AutoSelection | None = None


# Canonical names mapped to known physical aliases.  All identifiers originate
# here; callers cannot inject physical identifiers.
CUR_FIELDS: Mapping[str, tuple[str, ...]] = {
    "payer_account": ("bill_payer_account_id", "bill_payeraccountid"),
    "linked_account": ("line_item_usage_account_id", "lineitem_usageaccountid"),
    "linked_account_name": ("line_item_usage_account_name",),
    "billing_entity": ("bill_billing_entity", "bill_billingentity"),
    "legal_entity": ("line_item_legal_entity", "lineitem_legalentity"),
    "billing_period_start": ("bill_billing_period_start_date", "bill_billingperiodstartdate"),
    "billing_period_end": ("bill_billing_period_end_date", "bill_billingperiodenddate"),
    "usage_start": ("line_item_usage_start_date", "lineitem_usagestartdate"),
    "usage_end": ("line_item_usage_end_date", "lineitem_usageenddate"),
    "service_code": ("line_item_product_code", "lineitem_productcode"),
    "service_name": ("product_product_name", "product_productname"),
    "product_family": ("product_product_family", "product_productfamily"),
    "region": ("product_region", "product_region_code", "product_regioncode"),
    "availability_zone": ("line_item_availability_zone", "lineitem_availabilityzone"),
    "operation": ("line_item_operation", "lineitem_operation"),
    "usage_type": ("line_item_usage_type", "lineitem_usagetype"),
    "line_item_description": ("line_item_line_item_description", "lineitem_lineitemdescription"),
    "raw_line_item_type": ("line_item_line_item_type", "lineitem_lineitemtype"),
    "purchase_option": ("pricing_term",),
    "pricing_unit": ("pricing_unit",),
    "currency": ("line_item_currency_code", "lineitem_currencycode"),
    "usage_quantity": ("line_item_usage_amount", "lineitem_usageamount"),
    "resource_id": ("line_item_resource_id", "lineitem_resourceid"),
    "reservation_id": ("reservation_reservation_a_r_n", "reservation_reservationarn"),
    "savings_plan_id": ("savings_plan_savings_plan_a_r_n", "savingsplan_savingsplanarn"),
    "unblended_cost": ("line_item_unblended_cost", "lineitem_unblendedcost"),
    "net_unblended_cost": ("line_item_net_unblended_cost", "lineitem_netunblendedcost"),
    "blended_cost": ("line_item_blended_cost", "lineitem_blendedcost"),
    "public_on_demand_cost": (
        "pricing_public_on_demand_cost",
        "pricing_publicondemandcost",
    ),
    "reservation_effective_cost": (
        "reservation_effective_cost",
        "reservation_effectivecost",
    ),
    "reservation_unused_upfront": (
        "reservation_unused_amortized_upfront_fee_for_billing_period",
        "reservation_unusedamortizedupfrontfeeforbillingperiod",
    ),
    "reservation_unused_recurring": (
        "reservation_unused_recurring_fee",
        "reservation_unusedrecurringfee",
    ),
    "savings_plan_effective_cost": (
        "savings_plan_savings_plan_effective_cost",
        "savingsplan_savingsplaneffectivecost",
    ),
    "savings_plan_total_commitment": (
        "savings_plan_total_commitment_to_date",
        "savingsplan_totalcommitmenttodate",
    ),
    "savings_plan_used_commitment": (
        "savings_plan_used_commitment",
        "savingsplan_usedcommitment",
    ),
}

FOCUS_FIELDS: Mapping[str, tuple[str, ...]] = {
    "payer_account": ("BillingAccountId",),
    "linked_account": ("SubAccountId",),
    "linked_account_name": ("SubAccountName",),
    "billing_entity": ("InvoiceIssuerName",),
    "billing_period_start": ("BillingPeriodStart",),
    "billing_period_end": ("BillingPeriodEnd",),
    "usage_start": ("ChargePeriodStart",),
    "usage_end": ("ChargePeriodEnd",),
    "service_name": ("ServiceName",),
    "service_code": ("ServiceName",),
    "region": ("RegionId",),
    "availability_zone": ("AvailabilityZone",),
    "operation": ("SkuMeter",),
    "line_item_description": ("ChargeDescription",),
    "raw_line_item_type": ("ChargeClass",),
    "purchase_option": ("PricingCategory",),
    "pricing_unit": ("PricingUnit",),
    "currency": ("BillingCurrency",),
    "usage_quantity": ("ConsumedQuantity",),
    "resource_id": ("ResourceId",),
    "unblended_cost": ("BilledCost",),
    "effective_cost": ("EffectiveCost",),
    "public_on_demand_cost": ("ListCost",),
    "focus_charge_category": ("ChargeCategory",),
    "focus_charge_class": ("ChargeClass",),
    "focus_provider": ("ProviderName",),
}

CANONICAL_RAW_FIELDS = tuple(
    dict.fromkeys(
        (
            *CUR_FIELDS.keys(),
            *FOCUS_FIELDS.keys(),
            "effective_cost",
            "focus_charge_category",
            "focus_charge_class",
            "focus_provider",
        )
    )
)
CANONICAL_COLUMNS = CANONICAL_RAW_FIELDS + (
    "usage_date",
    "usage_month",
    "charge_category",
    "commitment_type",
    "amortized_cost",
    "source_schema",
    "source_schema_version",
    "relation_version",
    "classification_version",
)
NUMERIC_FIELDS = {
    "usage_quantity",
    "unblended_cost",
    "net_unblended_cost",
    "blended_cost",
    "public_on_demand_cost",
    "reservation_effective_cost",
    "reservation_unused_upfront",
    "reservation_unused_recurring",
    "savings_plan_effective_cost",
    "savings_plan_total_commitment",
    "savings_plan_used_commitment",
    "effective_cost",
}
TIMESTAMP_FIELDS = {
    "billing_period_start",
    "billing_period_end",
    "usage_start",
    "usage_end",
}
CUR2_MARKERS = {
    "bill_payer_account_name",
    "line_item_usage_account_name",
    "capacity_reservation_status",
    "resource_tags",
    "cost_category",
    "product",
}
FOCUS_REQUIRED = {
    "billing_period_start",
    "billing_period_end",
    "usage_start",
    "currency",
    "unblended_cost",
    "effective_cost",
    "focus_charge_category",
}
CUR_REQUIRED = {"usage_start", "raw_line_item_type", "currency"}


def _lookup(columns: Mapping[str, str], aliases: Sequence[str]) -> str | None:
    for alias in aliases:
        if alias.lower() in columns:
            return columns[alias.lower()]
    return None


def _resolved_fields(
    columns: Sequence[str], field_map: Mapping[str, tuple[str, ...]]
) -> dict[str, str]:
    physical = {column.lower(): column for column in columns}
    return {
        canonical: match
        for canonical, aliases in field_map.items()
        if (match := _lookup(physical, aliases)) is not None
    }


def detect_source_schema(columns: Sequence[str]) -> SourceSchema:
    """Detect exactly one supported billing schema from column evidence."""
    lowered = {column.lower() for column in columns}
    cur_fields = _resolved_fields(columns, CUR_FIELDS)
    focus_fields = _resolved_fields(columns, FOCUS_FIELDS)
    looks_cur = {"usage_start", "raw_line_item_type"} <= cur_fields.keys()
    looks_focus = {
        "unblended_cost",
        "effective_cost",
        "focus_charge_category",
    } <= focus_fields.keys()
    if looks_cur and looks_focus:
        raise AmbiguousSchemaError("columns satisfy both AWS CUR and AWS FOCUS signatures")
    if looks_focus:
        missing = tuple(sorted(FOCUS_REQUIRED - focus_fields.keys()))
        if missing:
            raise MissingRequiredFieldsError(missing)
        return SourceSchema(
            SourceSchemaType.FOCUS_1_0_AWS,
            "1.0",
            tuple(sorted(focus_fields)),
            optional_fields=tuple(sorted(set(FOCUS_FIELDS) - focus_fields.keys())),
            available_metrics=available_metrics(SourceSchemaType.FOCUS_1_0_AWS, focus_fields),
        )
    if looks_cur:
        missing = tuple(sorted(CUR_REQUIRED - cur_fields.keys()))
        if missing:
            raise MissingRequiredFieldsError(missing)
        source_type = (
            SourceSchemaType.CUR_2 if lowered & CUR2_MARKERS else SourceSchemaType.LEGACY_CUR
        )
        version = "2.0" if source_type is SourceSchemaType.CUR_2 else "legacy"
        return SourceSchema(
            source_type,
            version,
            tuple(sorted(cur_fields)),
            optional_fields=tuple(sorted(set(CUR_FIELDS) - cur_fields.keys())),
            available_metrics=available_metrics(source_type, cur_fields),
        )
    raise UnsupportedSchemaError("columns do not match legacy CUR, CUR 2.0, or AWS FOCUS 1.0")


def require_source_version(schema: SourceSchema, version: str) -> None:
    if schema.source_version != version:
        raise UnsupportedSourceVersionError(
            f"{schema.source_type.value} version {version!r} is unsupported; "
            f"detected {schema.source_version!r}"
        )


def _q(identifier: str) -> str:
    return '"' + identifier.replace('"', '""') + '"'


def _projection(field: str, physical: str | None) -> str:
    if physical is None:
        sql_type = (
            "DOUBLE"
            if field in NUMERIC_FIELDS
            else "TIMESTAMP"
            if field in TIMESTAMP_FIELDS
            else "VARCHAR"
        )
        return f"CAST(NULL AS {sql_type}) AS {_q(field)}"
    if field in NUMERIC_FIELDS:
        return f"TRY_CAST({_q(physical)} AS DOUBLE) AS {_q(field)}"
    if field in TIMESTAMP_FIELDS:
        return f"TRY_CAST({_q(physical)} AS TIMESTAMP) AS {_q(field)}"
    return f"TRY_CAST({_q(physical)} AS VARCHAR) AS {_q(field)}"


CHARGE_CATEGORY_SQL = """
CASE
 WHEN lower(coalesce(focus_charge_category, '')) = 'credit'
      OR raw_line_item_type = 'Credit' THEN 'credit'
 WHEN lower(coalesce(focus_charge_category, '')) = 'adjustment'
      OR raw_line_item_type = 'Refund' THEN
      CASE WHEN raw_line_item_type = 'Refund' THEN 'refund' ELSE 'adjustment' END
 WHEN lower(coalesce(focus_charge_category, '')) = 'tax'
      OR raw_line_item_type = 'Tax' THEN 'tax'
 WHEN lower(coalesce(service_name, '')) LIKE '%support%'
      OR lower(coalesce(line_item_description, '')) LIKE '%support%' THEN 'support'
 WHEN lower(coalesce(billing_entity, '')) LIKE '%marketplace%' THEN 'marketplace'
 WHEN raw_line_item_type = 'SavingsPlanCoveredUsage' THEN 'savings-plan-covered-usage'
 WHEN raw_line_item_type = 'DiscountedUsage' THEN 'reserved-instance-discounted-usage'
 WHEN raw_line_item_type = 'SavingsPlanRecurringFee' THEN
      CASE WHEN coalesce(savings_plan_total_commitment, 0)
                    - coalesce(savings_plan_used_commitment, 0) > 0
           THEN 'unused-commitment' ELSE 'recurring-commitment-fee' END
 WHEN raw_line_item_type = 'RIFee'
      AND coalesce(reservation_unused_upfront, 0)
          + coalesce(reservation_unused_recurring, 0) > 0 THEN 'unused-commitment'
 WHEN raw_line_item_type IN ('RIFee', 'Fee') THEN 'recurring-commitment-fee'
 WHEN raw_line_item_type IN ('SavingsPlanUpfrontFee', 'SavingsPlanNegation')
      THEN 'upfront-commitment-fee'
 WHEN raw_line_item_type IN ('BundledDiscount', 'Discount') THEN 'discount'
 WHEN lower(coalesce(focus_charge_category, '')) = 'usage'
      OR raw_line_item_type IN ('Usage', 'EdpDiscount') THEN 'usage'
 WHEN lower(coalesce(focus_charge_category, '')) = 'purchase' THEN 'fee'
 ELSE 'unknown'
END
""".strip()

AMORTIZED_SQL = """
CASE
 WHEN raw_line_item_type = 'SavingsPlanCoveredUsage'
      THEN savings_plan_effective_cost
 WHEN raw_line_item_type = 'SavingsPlanRecurringFee'
      THEN savings_plan_total_commitment - savings_plan_used_commitment
 WHEN raw_line_item_type IN ('SavingsPlanNegation', 'SavingsPlanUpfrontFee') THEN 0
 WHEN raw_line_item_type = 'DiscountedUsage' THEN reservation_effective_cost
 WHEN raw_line_item_type = 'RIFee'
      THEN coalesce(reservation_unused_upfront, 0)
           + coalesce(reservation_unused_recurring, 0)
 WHEN raw_line_item_type = 'Fee' AND reservation_id IS NOT NULL THEN 0
 ELSE unblended_cost
END
""".strip()


def build_canonical_relation(
    connection: Any, source: ParquetSource, relation_name: str = "reckoner_cost"
) -> CanonicalRelation:
    """Build a canonical DuckDB view from explicit Parquet objects."""
    raw_name = f"{relation_name}_raw"
    connection.from_parquet(
        list(source.locations),
        union_by_name=True,
        hive_partitioning=False,
    ).create_view(raw_name, replace=True)
    rows = connection.execute(f"DESCRIBE {_q(raw_name)}").fetchall()
    columns = [row[0] for row in rows]
    types = {str(row[0]): str(row[1]).upper() for row in rows}
    schema = detect_source_schema(columns)
    field_map = FOCUS_FIELDS if schema.source_type is SourceSchemaType.FOCUS_1_0_AWS else CUR_FIELDS
    resolved = _resolved_fields(columns, field_map)
    for field in TIMESTAMP_FIELDS & resolved.keys():
        physical_type = types[resolved[field]]
        if not any(token in physical_type for token in ("DATE", "TIME", "VARCHAR")):
            raise IncompatibleColumnTypeError(
                f"{resolved[field]} has incompatible type {physical_type}"
            )
    projection = ",\n".join(
        _projection(field, resolved.get(field)) for field in CANONICAL_RAW_FIELDS
    )
    source_schema = schema.source_type.value.replace("'", "''")
    source_version = schema.source_version.replace("'", "''")
    connection.execute(
        f"""
        CREATE OR REPLACE VIEW {_q(relation_name)} AS
        WITH projected AS (
          SELECT {projection}
          FROM {_q(raw_name)}
        )
        SELECT projected.*,
          CAST(usage_start AS DATE) AS usage_date,
          date_trunc('month', usage_start) AS usage_month,
          {CHARGE_CATEGORY_SQL} AS charge_category,
          CASE
            WHEN savings_plan_id IS NOT NULL THEN 'savings-plan'
            WHEN reservation_id IS NOT NULL THEN 'reserved-instance'
            ELSE NULL
          END AS commitment_type,
          {AMORTIZED_SQL} AS amortized_cost,
          '{source_schema}' AS source_schema,
          '{source_version}' AS source_schema_version,
          '{RELATION_VERSION}' AS relation_version,
          '{CLASSIFICATION_VERSION}' AS classification_version
        FROM projected
        """
    )
    return CanonicalRelation(relation_name, schema, source.source_kind)


CUR_SCHEMAS = (SourceSchemaType.LEGACY_CUR, SourceSchemaType.CUR_2)
ALL_SCHEMAS = (*CUR_SCHEMAS, SourceSchemaType.FOCUS_1_0_AWS)


def _formula(
    metric: str,
    expression: str,
    required: Sequence[str],
    schemas: Sequence[SourceSchemaType],
    included: Sequence[str],
    excluded: Sequence[str] = (),
    provenance: Sequence[str] = (),
    limitations: Sequence[str] = (),
) -> CostFormula:
    return CostFormula(
        metric,
        f"kulshan.{metric}",
        FORMULA_VERSION,
        expression,
        tuple(required),
        tuple(schemas),
        tuple(included),
        tuple(excluded),
        "Unavailable when a required component is absent; null input remains null.",
        "Preserve source currency; never convert; mixed currencies require grouping.",
        "Additive SUM after canonical row projection.",
        tuple(provenance),
        tuple(limitations),
    )


FORMULAS: Mapping[str, CostFormula] = {
    "unblended-cost": _formula(
        "unblended-cost", "unblended_cost", ("unblended_cost",), ALL_SCHEMAS, ("all",)
    ),
    "net-unblended-cost": _formula(
        "net-unblended-cost",
        "net_unblended_cost",
        ("net_unblended_cost",),
        CUR_SCHEMAS,
        ("all",),
    ),
    "blended-cost": _formula(
        "blended-cost", "blended_cost", ("blended_cost",), CUR_SCHEMAS, ("all",)
    ),
    "amortized-cost": _formula(
        "amortized-cost",
        "amortized_cost",
        (
            "unblended_cost",
            "reservation_effective_cost",
            "reservation_unused_upfront",
            "reservation_unused_recurring",
            "savings_plan_effective_cost",
            "savings_plan_total_commitment",
            "savings_plan_used_commitment",
        ),
        CUR_SCHEMAS,
        ("usage", "commitment fees", "covered usage"),
        ("SavingsPlanNegation", "SavingsPlanUpfrontFee", "RI-linked Fee"),
        ("cudos-amortized-cost-v1",),
        ("CUR-derived allocation is not final invoice reconciliation.",),
    ),
    "effective-cost": _formula(
        "effective-cost",
        "effective_cost",
        ("effective_cost",),
        (SourceSchemaType.FOCUS_1_0_AWS,),
        ("all FOCUS charges",),
        limitations=("Defined only for verified AWS FOCUS 1.0 input.",),
    ),
    "public-on-demand-cost": _formula(
        "public-on-demand-cost",
        "CASE WHEN raw_line_item_type = 'SavingsPlanNegation' THEN 0 "
        "ELSE public_on_demand_cost END",
        ("public_on_demand_cost",),
        ALL_SCHEMAS,
        ("all except SavingsPlanNegation",),
        ("SavingsPlanNegation",),
        ("cudos-public-on-demand-cost-v1",),
    ),
    "credits": _formula(
        "credits",
        "CASE WHEN charge_category = 'credit' THEN unblended_cost ELSE 0 END",
        ("unblended_cost",),
        ALL_SCHEMAS,
        ("credit",),
        ("non-credit",),
    ),
    "refunds": _formula(
        "refunds",
        "CASE WHEN charge_category = 'refund' THEN unblended_cost ELSE 0 END",
        ("unblended_cost", "raw_line_item_type"),
        CUR_SCHEMAS,
        ("refund",),
        ("non-refund",),
    ),
    "support": _formula(
        "support",
        "CASE WHEN charge_category = 'support' THEN unblended_cost ELSE 0 END",
        ("unblended_cost", "service_name"),
        ALL_SCHEMAS,
        ("support",),
        ("non-support",),
    ),
    "taxes": _formula(
        "taxes",
        "CASE WHEN charge_category = 'tax' THEN unblended_cost ELSE 0 END",
        ("unblended_cost",),
        ALL_SCHEMAS,
        ("tax",),
        ("non-tax",),
    ),
    "savings-plan-fees": _formula(
        "savings-plan-fees",
        "CASE WHEN raw_line_item_type IN "
        "('SavingsPlanRecurringFee','SavingsPlanUpfrontFee') "
        "THEN unblended_cost ELSE 0 END",
        ("unblended_cost", "raw_line_item_type"),
        CUR_SCHEMAS,
        ("SavingsPlanRecurringFee", "SavingsPlanUpfrontFee"),
    ),
    "reserved-instance-fees": _formula(
        "reserved-instance-fees",
        "CASE WHEN raw_line_item_type IN ('RIFee','Fee') "
        "AND reservation_id IS NOT NULL THEN unblended_cost ELSE 0 END",
        ("unblended_cost", "raw_line_item_type", "reservation_id"),
        CUR_SCHEMAS,
        ("RIFee", "RI-linked Fee"),
    ),
    "usage-quantity": _formula(
        "usage-quantity", "usage_quantity", ("usage_quantity",), ALL_SCHEMAS, ("all",)
    ),
}

PLANNED_UNAVAILABLE: Mapping[str, str] = {
    "invoiced-cost": (
        "CUR rows alone do not guarantee final invoice reconciliation, corrections, "
        "or Marketplace/support/tax treatment."
    ),
    "net-amortized-cost": (
        "No fully qualified cross-schema net amortization formula is adopted in PR 1."
    ),
    "unused-commitment-cost": (
        "Separate deterministic RI and Savings Plans qualification is incomplete."
    ),
}


def available_metrics(
    source_type: SourceSchemaType, fields: Mapping[str, str] | Sequence[str]
) -> tuple[str, ...]:
    names = set(fields)
    return tuple(
        sorted(
            metric
            for metric, formula in FORMULAS.items()
            if source_type in formula.supported_schemas
            and set(formula.required_components) <= names
        )
    )


def select_formula(
    relation: CanonicalRelation, metric: str
) -> tuple[CostFormula, AutoSelection | None]:
    available = set(relation.source.available_metrics)
    if metric != "auto":
        if metric not in FORMULAS:
            reason = PLANNED_UNAVAILABLE.get(metric, "metric is not registered")
            raise MetricUnavailableError(metric, relation.source.source_type.value, (reason,))
        formula = FORMULAS[metric]
        missing = tuple(
            sorted(set(formula.required_components) - set(relation.source.supported_fields))
        )
        if relation.source.source_type not in formula.supported_schemas or missing:
            raise MetricUnavailableError(metric, relation.source.source_type.value, missing)
        return formula, None
    order = ("amortized-cost", "net-unblended-cost", "unblended-cost")
    missing_by_metric: dict[str, tuple[str, ...]] = {}
    for candidate in order:
        formula = FORMULAS[candidate]
        missing = tuple(
            sorted(set(formula.required_components) - set(relation.source.supported_fields))
        )
        if relation.source.source_type in formula.supported_schemas and candidate in available:
            return formula, AutoSelection(
                candidate,
                order,
                missing_by_metric,
                "compatibility fallback selected the first fully qualified metric",
            )
        missing_by_metric[candidate] = missing or ("unsupported source schema",)
    raise MetricUnavailableError("auto", relation.source.source_type.value, tuple(order))


GROUPINGS: Mapping[str, str] = {
    "payer": "payer_account",
    "account": "linked_account",
    "account-name": "linked_account_name",
    "service": "service_name",
    "region": "region",
    "availability-zone": "availability_zone",
    "usage-type": "usage_type",
    "operation": "operation",
    "charge-type": "raw_line_item_type",
    "charge-category": "charge_category",
    "purchase-option": "purchase_option",
    "billing-entity": "billing_entity",
    "legal-entity": "legal_entity",
    "pricing-unit": "pricing_unit",
    "currency": "currency",
    "usage-date": "usage_date",
}


def query_metric(
    connection: Any,
    relation: CanonicalRelation,
    metric: str,
    *,
    groupings: Sequence[str] = (),
    period_start: str | None = None,
    period_end: str | None = None,
) -> CostMetricResult:
    formula, auto = select_formula(relation, metric)
    unknown = tuple(item for item in groupings if item not in GROUPINGS)
    if unknown:
        raise InvalidGroupingError(f"unsupported groupings: {', '.join(unknown)}")
    if len(set(groupings)) != len(groupings):
        raise InvalidGroupingError("duplicate groupings are not allowed")
    where = ["currency IS NOT NULL", "trim(currency) <> ''"]
    bindings: list[Any] = []
    if period_start is not None:
        where.append("usage_start >= CAST(? AS TIMESTAMP)")
        bindings.append(period_start)
    if period_end is not None:
        where.append("usage_start < CAST(? AS TIMESTAMP)")
        bindings.append(period_end)
    null_count = connection.execute(
        f"SELECT count(*) FROM {_q(relation.relation_name)} "
        "WHERE currency IS NULL OR trim(currency) = ''"
    ).fetchone()[0]
    if null_count:
        raise MissingCurrencyError("source contains null or malformed billing currency")
    currencies = tuple(
        row[0]
        for row in connection.execute(
            f"SELECT DISTINCT currency FROM {_q(relation.relation_name)} "
            "WHERE currency IS NOT NULL ORDER BY currency"
        ).fetchall()
    )
    if len(currencies) > 1 and "currency" not in groupings:
        raise MixedCurrencyError(
            "multiple billing currencies require currency grouping; conversion is forbidden"
        )
    columns = [GROUPINGS[item] for item in groupings]
    select_group = ", ".join(_q(item) for item in columns)
    select_prefix = f"{select_group}, " if select_group else ""
    group_by = f" GROUP BY {select_group}" if select_group else ""
    order_by = f" ORDER BY {select_group}" if select_group else ""
    sql = (
        f"SELECT {select_prefix}SUM({formula.expression}) AS value "
        f"FROM {_q(relation.relation_name)} WHERE {' AND '.join(where)}"
        f"{group_by}{order_by}"
    )
    cursor = connection.execute(sql, bindings)
    names = [item[0] for item in cursor.description]
    result_rows = tuple(dict(zip(names, row)) for row in cursor.fetchall())
    total = sum(float(row["value"] or 0) for row in result_rows)
    return CostMetricResult(
        formula.metric_id,
        formula.formula_id,
        formula.formula_version,
        currencies[0] if len(currencies) == 1 else None,
        result_rows,
        total,
        relation.source.source_type.value,
        relation.source.source_version,
        formula.limitations,
        auto,
    )


@contextmanager
def open_local_relation(
    source: ParquetSource, relation_name: str = "reckoner_cost"
) -> Iterator[tuple[Any, CanonicalRelation]]:
    import duckdb

    connection = duckdb.connect(":memory:")
    try:
        yield connection, build_canonical_relation(connection, source, relation_name)
    finally:
        connection.close()


@contextmanager
def open_s3_relation(
    source: ParquetSource,
    *,
    session: Any,
    relation_name: str = "reckoner_cost",
) -> Iterator[tuple[Any, CanonicalRelation]]:
    """Open an explicit manifest-pinned S3 relation with caller AWS session."""
    if source.source_kind != "s3":
        raise ValueError("open_s3_relation requires an S3 ParquetSource")
    from kulshan.cur.s3_query import connect_s3_duckdb

    connection = connect_s3_duckdb(session=session, region=source.region)
    try:
        yield connection, build_canonical_relation(connection, source, relation_name)
    finally:
        connection.close()


evaluate_metric = query_metric
