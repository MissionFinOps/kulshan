"""CUR column classification for consultant export.

Every column in the source CUR must be classified before export.
Unclassified columns BLOCK the export by default.

Classifications:
    SAFE         - value preserved as-is (costs, dates, service names, regions)
    PSEUDONYMIZE - value replaced with HMAC alias
    DROP         - column removed from output
    UNCLASSIFIED - column not in registry, blocks export
"""
from __future__ import annotations

import re
from enum import Enum


class ColumnClass(Enum):
    SAFE = "safe"
    PSEUDONYMIZE = "pseudonymize"
    DROP = "drop"
    UNCLASSIFIED = "unclassified"


# Tag key handling:
#   aws: prefixed keys -> key SAFE, values passthrough
#   allowlisted customer keys -> key passthrough, values pseudonymized
#   other customer keys -> UNCLASSIFIED (block)
ALLOWLISTED_TAG_KEYS = frozenset({
    "environment", "application", "team", "cost-center", "owner",
    "project", "service", "cost_center", "app", "env",
    "resource_tags_user_environment",
    "resource_tags_user_application",
    "resource_tags_user_team",
    "resource_tags_user_cost_center",
    "resource_tags_user_owner",
    "resource_tags_user_project",
    "resource_tags_user_service",
    "resource_tags_aws_createdby",
})

# Columns that are always safe (financial, temporal, categorical)
_SAFE_PREFIXES = (
    "bill_billing_period",
    "bill_bill_type",
    "bill_invoicing_entity",
    "identity_",
    "line_item_currency_code",
    "line_item_legal_entity",
    "line_item_line_item_description",
    "line_item_line_item_type",
    "line_item_net_",
    "line_item_normalization_factor",
    "line_item_normalized_usage_amount",
    "line_item_operation",
    "line_item_product_code",
    "line_item_tax_type",
    "line_item_unblended_",
    "line_item_blended_",
    "line_item_usage_account_name",  # pseudonymize below overrides
    "line_item_usage_amount",
    "line_item_usage_end_date",
    "line_item_usage_start_date",
    "line_item_usage_type",
    "lineitem_usagetype",
    "lineitem_usagestartdate",
    "lineitem_unblendedcost",
    "lineitem_blendedcost",
    "pricing_",
    "product_",
    "discount_",
    "savings_plan_savings_plan_rate",
    "savings_plan_offering_type",
    "savings_plan_payment_option",
    "savings_plan_purchase_term",
    "savings_plan_start_time",
    "savings_plan_end_time",
    "savings_plan_net_",
    "savings_plan_total_commitment_to_date",
    "savings_plan_used_commitment",
    "reservation_amortized_",
    "reservation_effective_cost",
    "reservation_net_",
    "reservation_number_of_reservations",
    "reservation_start_time",
    "reservation_end_time",
    "reservation_units_per_reservation",
    "reservation_total_reserved_units",
    "reservation_unused_",
    "cost_category_",
    "split_line_item_",
)

_SAFE_EXACT = frozenset({
    "billing_period",
    "cost",
    "usage_start_date",
    "usage_start",
    "usage_end_date",
    "usage_type",
    "service",
    "operation",
    "region",
    "availability_zone",
    "line_item_availability_zone",
    "product_region",
    "product_servicecode",
    "product_product_name",
    "line_item_line_item_id",
})

# Columns that must be pseudonymized (contain customer identifiers)
_PSEUDONYMIZE_EXACT = frozenset({
    "line_item_usage_account_id",
    "line_item_usage_account_name",
    "lineitem_usageaccountid",
    "bill_payer_account_id",
    "bill_payeraccountid",
    "linked_account_id",
    "usage_account_id",
    "payer_account_id",
    "line_item_resource_id",
    "lineitem_resourceid",
    "resource_id",
    "bill_invoice_id",
    "savings_plan_savings_plan_a_r_n",
    "reservation_reservation_a_r_n",
    "reservation_subscription_id",
})

_PSEUDONYMIZE_PREFIXES = (
    "resource_tags_",
)

# Columns to drop (not useful for investigation, potential risk)
_DROP_EXACT = frozenset({
    "identity_line_item_id",
    "identity_time_interval",
})


def classify_column(column_name: str, keep_tags: frozenset[str] = frozenset()) -> ColumnClass:
    """Classify a single CUR column for export treatment.

    Args:
        column_name: Lowercase column name from CUR schema.
        keep_tags: Set of tag key suffixes explicitly opted-in via --keep-tag.

    Returns:
        ColumnClass indicating how to handle this column.
    """
    col = column_name.lower()

    # Explicit pseudonymize takes priority over safe prefixes
    if col in _PSEUDONYMIZE_EXACT:
        return ColumnClass.PSEUDONYMIZE

    # Tag columns: resource_tags_*
    if col.startswith("resource_tags_"):
        tag_suffix = col[len("resource_tags_"):]
        # aws: prefixed tag keys are safe (values still pseudonymized in transform)
        if tag_suffix.startswith("aws_"):
            return ColumnClass.PSEUDONYMIZE  # values pseudonymized, key is safe
        # Allowlisted customer keys (check full column name and suffix variants)
        if col in ALLOWLISTED_TAG_KEYS or tag_suffix in keep_tags:
            return ColumnClass.PSEUDONYMIZE  # values pseudonymized
        # Also check without user_ prefix for --keep-tag convenience
        if tag_suffix.startswith("user_"):
            bare_key = tag_suffix[len("user_"):]
            if bare_key in keep_tags:
                return ColumnClass.PSEUDONYMIZE
        # Unknown customer tag key -> unclassified (block)
        return ColumnClass.UNCLASSIFIED

    # Pseudonymize prefixes
    for prefix in _PSEUDONYMIZE_PREFIXES:
        if col.startswith(prefix):
            return ColumnClass.PSEUDONYMIZE

    # Drop
    if col in _DROP_EXACT:
        return ColumnClass.DROP

    # Safe exact match
    if col in _SAFE_EXACT:
        return ColumnClass.SAFE

    # Safe prefix match
    for prefix in _SAFE_PREFIXES:
        if col.startswith(prefix):
            return ColumnClass.SAFE

    return ColumnClass.UNCLASSIFIED


def classify_all_columns(
    columns: set[str],
    keep_tags: frozenset[str] = frozenset(),
) -> dict[str, ColumnClass]:
    """Classify all columns in a CUR schema.

    Returns:
        Dict mapping column_name -> ColumnClass.
    """
    return {col: classify_column(col, keep_tags) for col in columns}
