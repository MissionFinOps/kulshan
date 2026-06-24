"""Topo check pack, VPC topology, CIDR overlaps, route integrity, flow-log coverage."""
from __future__ import annotations

import hashlib
from typing import List

__version__ = "0.1.0"
__all__ = ["__version__", "run_scan"]


def _fingerprint(pack: str, kind: str, resource_id: str) -> str:
    raw = f"{pack}|{kind}|{resource_id}"
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


def _extract_findings(result: dict) -> list:
    """Extract canonical findings from topology scan results."""
    findings = []

    # CIDR overlaps
    for item in result.get("cidr_overlaps", []):
        vpc_a = item.get("vpc_a", "unknown")
        vpc_b = item.get("vpc_b", "unknown")
        resource_id = f"{vpc_a}+{vpc_b}"
        fp = _fingerprint("topo", "cidr-overlap", resource_id)
        findings.append({
            "id": f"topo-cidr-overlap-{fp}",
            "pack": "topo",
            "kind": "cidr-overlap",
            "title": f"CIDR overlap between VPC '{vpc_a}' and '{vpc_b}'",
            "severity": "high",
            "confidence": 0.99,
            "effort": "high",
            "risk": "high",
            "resource_id": resource_id,
            "resource_arn": "",
            "region": item.get("region", "us-east-1"),
            "description": f"VPCs {vpc_a} ({item.get('cidr_a', '?')}) and {vpc_b} ({item.get('cidr_b', '?')}) have overlapping CIDR ranges. VPC peering is impossible.",
            "recommended_action": "Re-IP one of the VPCs or use a transit gateway with NAT.",
            "estimated_monthly_impact": 0,
            "fingerprint": fp,
        })

    # Route asymmetry
    for item in result.get("route_issues", []):
        resource_id = item.get("route_table_id", "unknown")
        fp = _fingerprint("topo", "route-asymmetry", resource_id)
        findings.append({
            "id": f"topo-route-asymmetry-{fp}",
            "pack": "topo",
            "kind": "route-asymmetry",
            "title": f"Route table '{resource_id}' has asymmetric or blackhole routes",
            "severity": "medium",
            "confidence": 0.85,
            "effort": "medium",
            "risk": "medium",
            "resource_id": resource_id,
            "resource_arn": "",
            "region": item.get("region", "us-east-1"),
            "description": item.get("reason", "Route table has potentially broken routes."),
            "recommended_action": "Review and fix route table entries.",
            "estimated_monthly_impact": 0,
            "fingerprint": fp,
        })

    # Missing VPC flow logs
    for item in result.get("no_flow_logs", []):
        resource_id = item.get("vpc_id", "unknown")
        fp = _fingerprint("topo", "no-flow-logs", resource_id)
        findings.append({
            "id": f"topo-no-flow-logs-{fp}",
            "pack": "topo",
            "kind": "no-flow-logs",
            "title": f"VPC '{resource_id}' has no flow logs enabled",
            "severity": "medium",
            "confidence": 0.99,
            "effort": "low",
            "risk": "safe",
            "resource_id": resource_id,
            "resource_arn": "",
            "region": item.get("region", "us-east-1"),
            "description": "VPC flow logs are not enabled. Network traffic cannot be audited.",
            "recommended_action": f"aws ec2 create-flow-logs --resource-type VPC --resource-ids {resource_id} --traffic-type ALL --log-destination-type cloud-watch-logs",
            "estimated_monthly_impact": 0,
            "fingerprint": fp,
        })

    return findings


def run_scan(session, regions: List[str], *, quick: bool = False, deep: bool = False, **kwargs) -> dict:
    """Run the network-topology scan and return a scored result dict."""
    from .scanner.topology import scan_topology
    from .scoring.engine import calculate_score

    if quick:
        regions = regions[:3]

    all_errors: list[str] = []
    try:
        result, errors = scan_topology(session, regions, estimate_transfer=deep)
        all_errors.extend(errors)
    except Exception as e:
        result = {}
        all_errors.append(str(e))

    scores = calculate_score(result) if result else {
        "overall_score": 100, "grade": "A+", "total_findings": 0,
        "severity_counts": {}, "breakdown": {},
    }

    findings = _extract_findings(result) if result else []

    sev: dict = {"critical": 0, "high": 0, "medium": 0, "low": 0, "info": 0}
    for f in findings:
        s = f.get("severity", "info")
        if s in sev:
            sev[s] += 1

    return {
        "tool": "topo",
        "findings": findings,
        "scores": {
            "overall_score": int(scores.get("overall_score", 0)),
            "grade": scores.get("grade", "N/A"),
            "total_findings": len(findings),
            "severity_counts": {k: v for k, v in sev.items() if v > 0},
            "breakdown": scores.get("breakdown", {}),
        },
        "errors": all_errors,
    }
