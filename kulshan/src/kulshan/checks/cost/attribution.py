"""Anomaly attribution for the cost pack.

Given a service-level statistical anomaly produced by ``analyzers.anomaly.detect_anomalies``,
drill down through the cost-explorer dimensions to identify the smallest dominant driver:

    service → linked account → region → usage_type → resource_id (best effort)

Each level requires one Cost Explorer call. Hard-capped at MAX_ATTRIBUTIONS_PER_SCAN
in cost.run_scan (Phase 6 Q1: default 5 anomalies attributed per scan).
"""
from __future__ import annotations

from typing import Any, Optional

import pandas as pd

# Threshold for "dominant driver", one value contributing >= this fraction of
# the total is treated as the cause. 0.60 = "more than half plus a clear margin."
DOMINANCE_THRESHOLD = 0.60


def find_dominant(
    df: pd.DataFrame, group_col: str, value_col: str = "cost"
) -> Optional[tuple[str, float]]:
    """Return ``(key, share)`` of the dominant value, or ``None`` if no clear driver.

    Share is in ``[0, 1]``; only returned when ``>= DOMINANCE_THRESHOLD``.
    """
    if df is None or df.empty:
        return None
    if group_col not in df.columns or value_col not in df.columns:
        return None
    totals = df.groupby(group_col)[value_col].sum()
    total = float(totals.sum())
    if total <= 0:
        return None
    top_key = totals.idxmax()
    share = float(totals[top_key] / total)
    if share < DOMINANCE_THRESHOLD:
        return None
    return str(top_key), share


def attribute_anomaly(
    fetcher: Any,
    anomaly_row: dict,
    *,
    days: int = 14,
) -> dict:
    """Attribute a service-level anomaly to its smallest dominant driver.

    ``fetcher`` is a :class:`CostFetcher` (or any duck-type with the methods
    used here). ``anomaly_row`` must include at least ``service``.

    Returns a dict with these keys (any may be ``None`` when no clear driver
    exists or when an upstream fetch fails):

    * ``account``, ``account_share``
    * ``region``, ``region_share``
    * ``usage_type``, ``usage_type_share``
    * ``resource_id`` (best-effort, compute service only)
    * ``notes``: list[str], human-readable trail of what was/wasn't found
    * ``api_calls``: int, number of CE calls made (for cost-budget tracking)
    """
    service = anomaly_row.get("service")
    out: dict = {
        "account": None,
        "account_share": None,
        "region": None,
        "region_share": None,
        "usage_type": None,
        "usage_type_share": None,
        "resource_id": None,
        "notes": [],
        "api_calls": 0,
    }
    if not service:
        out["notes"].append("missing service; cannot attribute")
        return out

    # Step 1: dominant linked account.
    try:
        df_acct = fetcher.get_cost_by_service_and_account(
            days=days, service_filter=service
        )
        out["api_calls"] += 1
    except Exception as e:
        out["notes"].append(f"account fetch failed: {e}")
        return out

    if df_acct is None or df_acct.empty:
        out["notes"].append("no service+account data returned")
    else:
        dom = find_dominant(df_acct, "account")
        if dom:
            out["account"] = dom[0]
            out["account_share"] = round(dom[1], 3)
        else:
            out["notes"].append("no dominant account (cost spread across accounts)")

    # Step 2: dominant region within (service).
    try:
        df_region = fetcher.get_cost_by_dimension(
            "region", days=days, service_filter=service
        )
        out["api_calls"] += 1
    except Exception as e:
        out["notes"].append(f"region fetch failed: {e}")
        df_region = pd.DataFrame()
    if df_region is not None and not df_region.empty:
        dom = find_dominant(df_region, "region")
        if dom:
            out["region"] = dom[0]
            out["region_share"] = round(dom[1], 3)
        else:
            out["notes"].append("no dominant region")

    # Step 3: dominant usage type within (service).
    try:
        df_usage = fetcher.get_cost_by_dimension(
            "usage_type", days=days, service_filter=service
        )
        out["api_calls"] += 1
    except Exception as e:
        out["notes"].append(f"usage_type fetch failed: {e}")
        df_usage = pd.DataFrame()
    if df_usage is not None and not df_usage.empty:
        dom = find_dominant(df_usage, "usage_type")
        if dom:
            out["usage_type"] = dom[0]
            out["usage_type_share"] = round(dom[1], 3)
        else:
            out["notes"].append("no dominant usage type")

    # Step 4: best-effort resource id (compute service only; opt-in API).
    if "Compute" in service:
        try:
            df_res = fetcher.get_top_resources(days=14)
            out["api_calls"] += 1
        except Exception as e:
            out["notes"].append(f"resource_id fetch unavailable: {e}")
            df_res = None
        if df_res is not None and not df_res.empty and "cost" in df_res.columns:
            top_resource = df_res.iloc[0]
            total = float(df_res["cost"].sum())
            if total > 0:
                share = float(top_resource["cost"]) / total
                if share >= DOMINANCE_THRESHOLD:
                    out["resource_id"] = str(top_resource["resource_id"])

    return out


def build_attribution_title(anomaly: dict, attribution: dict) -> str:
    """Render a human-readable title for an attributed anomaly.

    Examples:

    * ``EC2 - Other spike, 78% in account 000000000000, 95% in us-east-1, 88% USE1-NatGateway-Bytes``
    * ``Amazon RDS spike, (no clear single driver)``
    * ``AWS Lambda drop, 92% in eu-west-1``
    """
    service = anomaly.get("service") or "Unknown service"
    pct = anomaly.get("pct_change", 0)
    try:
        direction = "spike" if float(pct) >= 0 else "drop"
    except (TypeError, ValueError):
        direction = "spike"

    bits: list[str] = []
    if attribution.get("account"):
        share_pct = int(round((attribution.get("account_share") or 0) * 100))
        bits.append(f"{share_pct}% in account {attribution['account']}")
    if attribution.get("region"):
        share_pct = int(round((attribution.get("region_share") or 0) * 100))
        bits.append(f"{share_pct}% in {attribution['region']}")
    if attribution.get("usage_type"):
        share_pct = int(round((attribution.get("usage_type_share") or 0) * 100))
        bits.append(f"{share_pct}% {attribution['usage_type']}")

    if bits:
        return f"{service} {direction}, " + ", ".join(bits)
    return f"{service} {direction}, (no clear single driver)"


def recommend_action(anomaly: dict, attribution: dict) -> str:
    """Return a conservative, attribution-aware recommendation.

    Recommends investigation rather than action. Specific per-usage-type
    recommendations can be added in a later phase.
    """
    if not attribution.get("account"):
        svc = anomaly.get("service", "this service")
        return (
            f"Investigate {svc} cost change; no single account drives it. "
            "Compare per-account spend over the anomaly window."
        )
    parts = [f"Investigate in account {attribution['account']}"]
    if attribution.get("region"):
        parts.append(f"region {attribution['region']}")
    if attribution.get("usage_type"):
        parts.append(f"usage type {attribution['usage_type']}")
    if attribution.get("resource_id"):
        parts.append(f"resource {attribution['resource_id']}")
    return ", ".join(parts) + "."
