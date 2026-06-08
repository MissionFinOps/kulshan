"""Tag-based cost attribution — answers "who owns what spend?"

Uses Cost Explorer with TAG grouping to identify unattributed spend
and tag-based cost spikes. The #1 FinOps question.
"""
from __future__ import annotations

import hashlib
from typing import Any, Dict, List


def analyze_tag_attribution(fetcher: Any, days: int = 30) -> Dict[str, Any]:
    """Analyze cost attribution by tags.

    Returns:
    - unattributed_pct: % of spend with no cost allocation tags
    - top_tags: top tag values by spend
    - findings: canonical findings for attribution issues
    """
    findings: List[dict] = []
    errors: List[str] = []

    # Try common cost allocation tag keys
    tag_keys_to_try = ["Team", "Project", "Environment", "Owner", "CostCenter", "Department"]

    total_spend = 0.0
    tagged_spend = 0.0
    tag_breakdown: Dict[str, Dict[str, float]] = {}

    for tag_key in tag_keys_to_try:
        try:
            tag_data = fetcher.get_cost_by_tag(tag_key=tag_key, days=days)
            if tag_data is None or tag_data.empty:
                continue

            for _, row in tag_data.iterrows():
                tag_value = str(row.get("tag_value", "")).strip()
                cost = float(row.get("cost", 0))

                if tag_key not in tag_breakdown:
                    tag_breakdown[tag_key] = {}

                if tag_value and tag_value not in ("", "None", "N/A"):
                    tag_breakdown[tag_key][tag_value] = tag_breakdown[tag_key].get(tag_value, 0) + cost
                    tagged_spend += cost

                total_spend += cost

        except Exception as e:
            errors.append(f"Tag attribution ({tag_key}): {e}")
            continue

    # If we couldn't get any tag data, try total spend from other method
    if total_spend == 0:
        try:
            total_spend = fetcher.get_total_spend(days=days)
        except Exception:
            pass

    # Calculate unattributed percentage
    unattributed_pct = 0.0
    if total_spend > 0:
        unattributed_spend = total_spend - tagged_spend
        unattributed_pct = (unattributed_spend / total_spend) * 100

    # Top tag values across all keys
    all_tags: List[Dict[str, Any]] = []
    for tag_key, values in tag_breakdown.items():
        for tag_value, cost in sorted(values.items(), key=lambda x: -x[1])[:5]:
            all_tags.append({"key": tag_key, "value": tag_value, "monthly_cost": cost})

    all_tags.sort(key=lambda x: -x["monthly_cost"])
    top_tags = all_tags[:10]

    # Generate findings
    if unattributed_pct > 30 and total_spend > 1000:
        unattributed_dollars = total_spend * (unattributed_pct / 100)
        fp = hashlib.sha256(f"cost|unattributed-spend|{unattributed_pct:.0f}".encode()).hexdigest()[:16]
        findings.append({
            "id": f"cost-unattributed-spend-{fp}",
            "pack": "cost",
            "kind": "unattributed-spend",
            "title": f"{unattributed_pct:.0f}% of spend (${unattributed_dollars:,.0f}/mo) has no cost allocation tags",
            "severity": "high" if unattributed_pct > 50 else "medium",
            "confidence": 0.90,
            "effort": "medium",
            "risk": "safe",
            "resource_id": "unattributed-spend",
            "resource_arn": "",
            "region": "global",
            "description": f"{unattributed_pct:.0f}% of AWS spend cannot be attributed to a team or project. This makes cost accountability impossible.",
            "recommended_action": "Enable cost allocation tags (Team, Project, Environment) and enforce them via AWS Organizations tag policies.",
            "estimated_monthly_impact": unattributed_dollars * 0.1,  # Visibility alone typically saves 10%
            "fingerprint": fp,
            "metadata": {
                "unattributed_pct": unattributed_pct,
                "total_spend": total_spend,
                "tagged_spend": tagged_spend,
            },
        })

    return {
        "unattributed_pct": unattributed_pct,
        "total_spend": total_spend,
        "tagged_spend": tagged_spend,
        "top_tags": top_tags,
        "tag_breakdown": tag_breakdown,
        "findings": findings,
        "errors": errors,
    }
