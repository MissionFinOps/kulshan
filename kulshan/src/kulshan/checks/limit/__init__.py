"""Limit check pack, service quota usage, scaling-event headroom, non-adjustable hard ceilings."""
from __future__ import annotations

import hashlib
from typing import List

__version__ = "0.1.0"
__all__ = ["__version__", "run_scan"]


def _fingerprint(pack: str, kind: str, resource_id: str) -> str:
    raw = f"{pack}|{kind}|{resource_id}"
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


def _quota_to_finding(quota: dict) -> dict:
    """Convert a quota dict to a canonical finding."""
    service = quota.get("service_code", "unknown")
    quota_name = quota.get("quota_name", "Unknown quota")
    usage_pct = quota.get("usage_percent", 0)
    current = quota.get("current_value", 0)
    limit_val = quota.get("limit_value", 0)
    region = quota.get("region", "us-east-1")
    status = quota.get("status", "ok")  # "critical", "warning", "ok"

    if status == "critical":
        severity = "critical"
        kind = "quota-critical"
    else:
        severity = "high"
        kind = "quota-near-limit"

    resource_id = f"{service}/{quota_name}"
    fp = _fingerprint("limit", kind, resource_id)

    return {
        "id": f"limit-{kind}-{fp}",
        "pack": "limit",
        "kind": kind,
        "title": f"{service} quota '{quota_name}' at {usage_pct:.0f}% ({current}/{limit_val})",
        "severity": severity,
        "confidence": 0.99,
        "effort": "low",
        "risk": "safe",
        "resource_id": resource_id,
        "resource_arn": "",
        "region": region,
        "description": f"Service quota is at {usage_pct:.0f}% utilization. Request an increase before hitting the limit.",
        "recommended_action": f"aws service-quotas request-service-quota-increase --service-code {service} --quota-code {quota.get('quota_code', 'UNKNOWN')} --desired-value {int(limit_val * 1.5)} --region {region}",
        "estimated_monthly_impact": 0,
        "fingerprint": fp,
        "metadata": {
            "service": service,
            "quota_code": quota.get("quota_code", ""),
            "current_value": current,
            "limit_value": limit_val,
            "usage_percent": usage_pct,
        },
    }


def run_scan(session, regions: List[str], *, quick: bool = False, **kwargs) -> dict:
    """Run the quota/headroom scan and return a scored result dict."""
    from .scanner.quotas import scan_quotas
    from .scoring.engine import calculate_score

    if quick:
        regions = regions[:3]

    all_errors: list[str] = []
    try:
        quotas, errors = scan_quotas(session, regions, quick=quick)
        all_errors.extend(errors)
    except Exception as e:
        quotas = []
        all_errors.append(str(e))

    scores = calculate_score(quotas) if quotas else {
        "overall_score": 100, "grade": "A+", "total_quotas_checked": 0,
        "counts": {}, "breakdown": {},
    }

    # Convert at-risk quotas to canonical findings
    findings = []
    for q in quotas:
        status = q.get("status", "ok")
        if status in ("critical", "warning"):
            findings.append(_quota_to_finding(q))

    sev: dict = {"critical": 0, "high": 0, "medium": 0, "low": 0, "info": 0}
    for f in findings:
        s = f.get("severity", "info")
        if s in sev:
            sev[s] += 1

    return {
        "tool": "limit",
        "findings": findings,
        "scores": {
            "overall_score": int(scores.get("overall_score", 100)),
            "grade": scores.get("grade", "A+"),
            "total_findings": len(findings),
            "severity_counts": {k: v for k, v in sev.items() if v > 0},
            "breakdown": scores.get("breakdown", {}),
        },
        "errors": all_errors,
    }
