"""Age check pack, Lambda runtimes, RDS engines, ACM certificates, EBS modernization."""
from __future__ import annotations

import hashlib
from typing import List

__version__ = "0.1.0"
__all__ = ["__version__", "run_scan"]


def _fingerprint(pack: str, kind: str, resource_id: str) -> str:
    raw = f"{pack}|{kind}|{resource_id}"
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


def _extract_findings(result: dict) -> list:
    """Extract canonical findings from freshness scan results."""
    findings = []

    # EOL runtimes (Lambda, RDS engines, EKS versions)
    for item in result.get("eol_runtimes", []):
        resource_id = item.get("resource_id", "unknown")
        fp = _fingerprint("age", "eol-runtime", resource_id)
        days_past = item.get("days_past_eol", 0)
        severity = "critical" if days_past > 180 else "high" if days_past > 0 else "medium"
        findings.append({
            "id": f"age-eol-runtime-{fp}",
            "pack": "age",
            "kind": "eol-runtime",
            "title": f"{item.get('resource_type', 'Resource')} '{resource_id}' uses EOL runtime ({item.get('runtime', '?')})",
            "severity": severity,
            "confidence": 0.99,
            "effort": "medium",
            "risk": "medium",
            "resource_id": resource_id,
            "resource_arn": item.get("resource_arn", ""),
            "region": item.get("region", "us-east-1"),
            "description": f"Runtime '{item.get('runtime', '?')}' is end-of-life ({days_past} days past EOL). No security patches.",
            "recommended_action": f"Upgrade to a supported runtime version.",
            "estimated_monthly_impact": 0,
            "fingerprint": fp,
        })

    # Expiring certificates
    for item in result.get("expiring_certs", []):
        resource_id = item.get("resource_id", "unknown")
        fp = _fingerprint("age", "expiring-certificate", resource_id)
        days_left = item.get("days_until_expiry", 0)
        severity = "critical" if days_left <= 7 else "high" if days_left <= 30 else "medium"
        findings.append({
            "id": f"age-expiring-certificate-{fp}",
            "pack": "age",
            "kind": "expiring-certificate",
            "title": f"Certificate '{resource_id}' expires in {days_left} days",
            "severity": severity,
            "confidence": 0.99,
            "effort": "low",
            "risk": "safe",
            "resource_id": resource_id,
            "resource_arn": item.get("resource_arn", ""),
            "region": item.get("region", "us-east-1"),
            "description": f"ACM certificate expires in {days_left} days. Renew or enable auto-renewal.",
            "recommended_action": f"aws acm renew-certificate --certificate-arn {item.get('resource_arn', resource_id)}",
            "estimated_monthly_impact": 0,
            "fingerprint": fp,
        })

    # Stale AMIs
    for item in result.get("stale_amis", []):
        resource_id = item.get("resource_id", "unknown")
        fp = _fingerprint("age", "stale-ami", resource_id)
        age_days = item.get("age_days", 0)
        findings.append({
            "id": f"age-stale-ami-{fp}",
            "pack": "age",
            "kind": "stale-ami",
            "title": f"AMI '{resource_id}' is {age_days} days old and unused",
            "severity": "low",
            "confidence": 0.70,
            "effort": "trivial",
            "risk": "low",
            "resource_id": resource_id,
            "resource_arn": "",
            "region": item.get("region", "us-east-1"),
            "description": f"AMI is {age_days} days old and not used by any running instance.",
            "recommended_action": f"aws ec2 deregister-image --image-id {resource_id}",
            "estimated_monthly_impact": 0,
            "fingerprint": fp,
        })

    return findings


def run_scan(session, regions: List[str], *, quick: bool = False, **kwargs) -> dict:
    """Run the lifecycle/staleness scan and return a scored result dict."""
    from .scanner.freshness import scan_freshness
    from .scoring.engine import calculate_score

    if quick:
        regions = regions[:3]

    all_errors: list[str] = []
    try:
        result, errors = scan_freshness(session, regions)
        all_errors.extend(errors)
    except Exception as e:
        result = {}
        all_errors.append(str(e))

    scores = calculate_score(result) if result else {
        "overall_score": 100, "grade": "A+", "total_aging": 0,
        "severity_counts": {}, "breakdown": {},
    }

    findings = _extract_findings(result) if result else []

    sev: dict = {"critical": 0, "high": 0, "medium": 0, "low": 0, "info": 0}
    for f in findings:
        s = f.get("severity", "info")
        if s in sev:
            sev[s] += 1

    return {
        "tool": "age",
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
