"""Cost impact analysis, the Dark Money report."""

from typing import Dict, List
from ..utils.aws import safe_api_call


def analyze_cost_impact(session, resources, required_tags=None):
    """Calculate how much spend is unattributable due to missing tags."""
    if required_tags is None:
        required_tags = ["CostCenter", "Owner", "Environment"]

    ce = session.client("ce", region_name="us-east-1")

    # Get total monthly spend
    import datetime
    end = datetime.date.today().replace(day=1)
    start = (end - datetime.timedelta(days=32)).replace(day=1)

    total_resp, err = safe_api_call(ce, "get_cost_and_usage",
        TimePeriod={"Start": start.isoformat(), "End": end.isoformat()},
        Granularity="MONTHLY", Metrics=["UnblendedCost"])

    total_spend = 0
    if not err and total_resp:
        for result in total_resp.get("ResultsByTime", []):
            total_spend += float(result.get("Total", {}).get("UnblendedCost", {}).get("Amount", 0))

    # Get spend grouped by a key tag (CostCenter or first required tag)
    cost_tag = required_tags[0] if required_tags else "CostCenter"
    tagged_resp, err2 = safe_api_call(ce, "get_cost_and_usage",
        TimePeriod={"Start": start.isoformat(), "End": end.isoformat()},
        Granularity="MONTHLY", Metrics=["UnblendedCost"],
        GroupBy=[{"Type": "TAG", "Key": cost_tag}])

    tagged_spend = 0
    untagged_spend = 0
    tag_breakdown = {}
    if not err2 and tagged_resp:
        for result in tagged_resp.get("ResultsByTime", []):
            for group in result.get("Groups", []):
                key_val = group["Keys"][0]
                amount = float(group["Metrics"]["UnblendedCost"]["Amount"])
                # Empty tag key means untagged
                tag_name = key_val.replace(f"{cost_tag}$", "")
                if not tag_name or tag_name == "":
                    untagged_spend += amount
                else:
                    tagged_spend += amount
                    tag_breakdown[tag_name] = tag_breakdown.get(tag_name, 0) + amount

    # Calculate dark money
    dark_money_pct = (untagged_spend / total_spend * 100) if total_spend > 0 else 0

    return {
        "total_monthly_spend": total_spend,
        "tagged_spend": tagged_spend,
        "untagged_spend": untagged_spend,
        "dark_money_pct": dark_money_pct,
        "cost_tag_used": cost_tag,
        "tag_breakdown": dict(sorted(tag_breakdown.items(), key=lambda x: -x[1])),
        "period": f"{start.isoformat()} to {end.isoformat()}",
        "error": err or err2,
    }
