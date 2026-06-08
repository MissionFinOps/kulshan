"""Network cost deep-dive, categorize VPC, data transfer, NAT, endpoint costs."""
from __future__ import annotations

import pandas as pd


# Usage type patterns for categorization
_CATEGORIES = {
    "nat_gateway": ["NatGateway"],
    "vpc_endpoint": ["VpcEndpoint", "VPCEndpoint"],
    "data_transfer_out": ["DataTransfer-Out", "AWS-Out"],
    "data_transfer_inter_region": ["DataTransfer-Regional", "InterRegion"],
    "transit_gateway": ["TransitGateway"],
    "cloud_wan": ["CloudWAN", "CoreNetwork"],
    "network_firewall": ["Metering", "NetworkFirewall"],
    "route53": ["DNS-Queries", "HostedZone", "ResolverNetworkInterface"],
}


def categorize_network_costs(df: pd.DataFrame) -> dict:
    """
    Categorize network costs from usage_type data into meaningful buckets.
    Returns dict with category totals and details.
    """
    if df.empty:
        return {}

    categories = {}
    uncategorized = []

    for _, row in df.iterrows():
        usage = str(row.get("usage_type", ""))
        cost = row["cost"]
        service = row.get("service", "")
        matched = False

        for cat, patterns in _CATEGORIES.items():
            if any(p.lower() in usage.lower() for p in patterns):
                if cat not in categories:
                    categories[cat] = {"total": 0, "items": []}
                categories[cat]["total"] += cost
                categories[cat]["items"].append({"usage_type": usage, "cost": cost, "service": service})
                matched = True
                break

        if not matched:
            uncategorized.append({"usage_type": usage, "cost": cost, "service": service})

    # Add uncategorized as "other_network"
    if uncategorized:
        categories["other_network"] = {
            "total": sum(i["cost"] for i in uncategorized),
            "items": uncategorized,
        }

    grand_total = sum(c["total"] for c in categories.values())

    return {
        "grand_total": round(grand_total, 2),
        "categories": {
            k: {"total": round(v["total"], 2), "pct": round(v["total"] / grand_total * 100, 1) if grand_total > 0 else 0, "items": v["items"]}
            for k, v in sorted(categories.items(), key=lambda x: x[1]["total"], reverse=True)
        },
    }


_CATEGORY_LABELS = {
    "nat_gateway": "NAT Gateway",
    "vpc_endpoint": "VPC Endpoints",
    "data_transfer_out": "Internet Egress",
    "data_transfer_inter_region": "Inter-Region Transfer",
    "transit_gateway": "Transit Gateway",
    "cloud_wan": "Cloud WAN",
    "network_firewall": "Network Firewall",
    "route53": "Route 53 / DNS",
    "other_network": "Other Network",
}


def get_category_label(key: str) -> str:
    return _CATEGORY_LABELS.get(key, key.replace("_", " ").title())
