"""Tag check pack, tag compliance, dark money (untagged spend), value chaos detection."""
from __future__ import annotations

import hashlib
from typing import List

__version__ = "0.1.0"
__all__ = ["__version__", "run_scan"]


def _fingerprint(pack: str, kind: str, resource_id: str) -> str:
    raw = f"{pack}|{kind}|{resource_id}"
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


def _empty(reason: str) -> dict:
    return {
        "tool": "tag",
        "findings": [],
        "scores": {"overall_score": 0, "grade": "N/A", "total_findings": 0, "severity_counts": {}},
        "errors": [reason],
        "skipped": True,
    }


def _extract_findings(compliance: dict, resources: list) -> list:
    """Extract canonical findings from tag compliance analysis."""
    findings = []

    # Untagged resources (no tags at all)
    for item in compliance.get("untagged_resources", []):
        resource_arn = item.get("resource_arn", "unknown")
        resource_id = resource_arn.split("/")[-1] if "/" in resource_arn else resource_arn.split(":")[-1]
        fp = _fingerprint("tag", "untagged-resource", resource_id)
        findings.append({
            "id": f"tag-untagged-resource-{fp}",
            "pack": "tag",
            "kind": "untagged-resource",
            "title": f"Resource '{resource_id}' has no tags",
            "severity": "medium",
            "confidence": 0.99,
            "effort": "trivial",
            "risk": "safe",
            "resource_id": resource_id,
            "resource_arn": resource_arn,
            "region": item.get("region", "us-east-1"),
            "description": "This resource has zero tags. Cannot be attributed to a team, project, or environment.",
            "recommended_action": f"aws resourcegroupstaggingapi tag-resources --resource-arn-list {resource_arn} --tags Environment=unknown,Owner=unknown",
            "estimated_monthly_impact": 0,
            "fingerprint": fp,
        })

    # Missing required tags (has some tags but missing critical ones)
    for item in compliance.get("missing_required", []):
        resource_arn = item.get("resource_arn", "unknown")
        resource_id = resource_arn.split("/")[-1] if "/" in resource_arn else resource_arn.split(":")[-1]
        missing = item.get("missing_tags", [])
        fp = _fingerprint("tag", "missing-cost-allocation", resource_id)
        findings.append({
            "id": f"tag-missing-cost-allocation-{fp}",
            "pack": "tag",
            "kind": "missing-cost-allocation",
            "title": f"Resource '{resource_id}' missing tags: {', '.join(missing[:3])}",
            "severity": "low",
            "confidence": 0.95,
            "effort": "trivial",
            "risk": "safe",
            "resource_id": resource_id,
            "resource_arn": resource_arn,
            "region": item.get("region", "us-east-1"),
            "description": f"Missing required cost allocation tags: {', '.join(missing)}.",
            "recommended_action": "Add the missing tags for cost attribution and governance.",
            "estimated_monthly_impact": 0,
            "fingerprint": fp,
        })

    return findings


def run_scan(session, regions: List[str], *, quick: bool = False, **kwargs) -> dict:
    """Run the tag-compliance scan and return a scored result dict."""
    from .scanner.tagging_api import scan_all_resources, get_all_tag_keys
    from .analysis.compliance import analyze_compliance
    from .analysis.consistency import analyze_consistency
    from .scoring.engine import calculate_score

    if quick:
        regions = regions[:3]

    all_errors: list[str] = []
    try:
        resources, errors = scan_all_resources(session, regions)
        all_errors.extend(errors)
    except Exception as e:
        return _empty(str(e))

    required_tags = ["Name", "Environment", "Owner", "CostCenter"]

    try:
        tag_keys = get_all_tag_keys(session, regions)
    except Exception:
        tag_keys = required_tags

    compliance = analyze_compliance(resources, required_tags)
    consistency = analyze_consistency(resources, tag_keys)

    cost_impact: dict = {}
    if not quick:
        try:
            from .analysis.cost_impact import analyze_cost_impact
            cost_impact = analyze_cost_impact(session, resources, required_tags)
        except Exception as e:
            all_errors.append(f"Cost impact: {e}")

    scores = calculate_score(compliance, consistency, cost_impact)
    findings = _extract_findings(compliance, resources)

    sev: dict = {"critical": 0, "high": 0, "medium": 0, "low": 0, "info": 0}
    for f in findings:
        s = f.get("severity", "info")
        if s in sev:
            sev[s] += 1

    return {
        "tool": "tag",
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
