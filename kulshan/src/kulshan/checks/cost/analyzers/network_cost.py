"""Data transfer cost decomposition — reveals hidden networking spend.

Breaks out cross-AZ, NAT Gateway, internet egress, and S3 transfer costs
which are often 15-25% of total spend but invisible in standard views.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional


def analyze_data_transfer(fetcher: Any, days: int = 30) -> Dict[str, Any]:
    """Analyze data transfer costs by category.

    Returns a dict with:
    - total_transfer_cost: total $ on data transfer
    - pct_of_total: data transfer as % of total bill
    - breakdown: {category: cost} for each transfer type
    - findings: list of canonical finding dicts for anomalous transfer spend
    """
    import hashlib

    errors: List[str] = []
    findings: List[dict] = []

    try:
        # Fetch cost grouped by usage type, filtered to transfer-related types
        transfer_data = fetcher.get_cost_by_usage_type_filter(
            days=days,
            usage_type_contains=["DataTransfer", "NatGateway", "Bytes", "Transfer"],
        )
    except Exception as e:
        return {
            "total_transfer_cost": 0,
            "pct_of_total": 0,
            "breakdown": {},
            "findings": [],
            "errors": [f"Data transfer analysis: {e}"],
        }

    if transfer_data is None or transfer_data.empty:
        return {
            "total_transfer_cost": 0,
            "pct_of_total": 0,
            "breakdown": {},
            "findings": [],
            "errors": errors,
        }

    # Categorize transfer types
    categories: Dict[str, float] = {
        "internet_egress": 0.0,
        "cross_az": 0.0,
        "nat_gateway": 0.0,
        "s3_transfer": 0.0,
        "vpc_endpoint": 0.0,
        "other_transfer": 0.0,
    }

    for _, row in transfer_data.iterrows():
        usage_type = str(row.get("usage_type", "")).lower()
        cost = float(row.get("cost", 0))

        if "natgateway" in usage_type:
            categories["nat_gateway"] += cost
        elif "cross" in usage_type or "interzone" in usage_type or "-az" in usage_type:
            categories["cross_az"] += cost
        elif "s3" in usage_type or "bucket" in usage_type:
            categories["s3_transfer"] += cost
        elif "vpce" in usage_type or "endpoint" in usage_type:
            categories["vpc_endpoint"] += cost
        elif "out" in usage_type or "egress" in usage_type or "internet" in usage_type:
            categories["internet_egress"] += cost
        else:
            categories["other_transfer"] += cost

    total_transfer = sum(categories.values())

    # Get total spend for percentage calculation
    try:
        total_spend = fetcher.get_total_spend(days=days)
    except Exception:
        total_spend = 1.0  # Avoid division by zero

    pct_of_total = (total_transfer / total_spend * 100) if total_spend > 0 else 0

    # Generate findings for high transfer costs
    if pct_of_total >= 20:
        fp = hashlib.sha256(f"cost|high-data-transfer|{pct_of_total:.0f}".encode()).hexdigest()[:16]
        findings.append({
            "id": f"cost-high-data-transfer-{fp}",
            "pack": "cost",
            "kind": "high-data-transfer",
            "title": f"Data transfer is {pct_of_total:.0f}% of total spend (${total_transfer:,.0f}/mo)",
            "severity": "high",
            "confidence": 0.95,
            "effort": "medium",
            "risk": "safe",
            "resource_id": "data-transfer",
            "resource_arn": "",
            "region": "global",
            "description": f"Networking costs (transfer, NAT, cross-AZ) represent {pct_of_total:.0f}% of your bill. Industry average is 8-12%.",
            "recommended_action": "Review cross-AZ traffic patterns, consider VPC endpoints for S3/DynamoDB, and evaluate NAT Gateway alternatives.",
            "estimated_monthly_impact": total_transfer * 0.3,  # Assume 30% is optimizable
            "fingerprint": fp,
            "metadata": {"breakdown": categories, "pct_of_total": pct_of_total},
        })

    if categories["nat_gateway"] > 500:
        fp = hashlib.sha256(f"cost|high-nat-cost|{categories['nat_gateway']:.0f}".encode()).hexdigest()[:16]
        findings.append({
            "id": f"cost-high-nat-cost-{fp}",
            "pack": "cost",
            "kind": "high-nat-cost",
            "title": f"NAT Gateway costs ${categories['nat_gateway']:,.0f}/mo",
            "severity": "medium",
            "confidence": 0.90,
            "effort": "medium",
            "risk": "low",
            "resource_id": "nat-gateway-spend",
            "resource_arn": "",
            "region": "global",
            "description": "NAT Gateway charges $0.045/GB processed plus $0.045/hr. Consider VPC endpoints or NAT instances for high-volume traffic.",
            "recommended_action": "Add S3/DynamoDB VPC endpoints to eliminate NAT charges for those services.",
            "estimated_monthly_impact": categories["nat_gateway"] * 0.4,
            "fingerprint": fp,
        })

    if categories["cross_az"] > 300:
        fp = hashlib.sha256(f"cost|high-cross-az|{categories['cross_az']:.0f}".encode()).hexdigest()[:16]
        findings.append({
            "id": f"cost-high-cross-az-{fp}",
            "pack": "cost",
            "kind": "high-cross-az",
            "title": f"Cross-AZ transfer costs ${categories['cross_az']:,.0f}/mo",
            "severity": "medium",
            "confidence": 0.85,
            "effort": "high",
            "risk": "medium",
            "resource_id": "cross-az-spend",
            "resource_arn": "",
            "region": "global",
            "description": "Cross-AZ data transfer costs $0.01/GB in each direction. Co-locating services in the same AZ reduces this.",
            "recommended_action": "Review service placement. Consider AZ-affinity for high-bandwidth services.",
            "estimated_monthly_impact": categories["cross_az"] * 0.5,
            "fingerprint": fp,
        })

    return {
        "total_transfer_cost": total_transfer,
        "pct_of_total": pct_of_total,
        "breakdown": categories,
        "findings": findings,
        "errors": errors,
    }
