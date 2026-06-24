"""Drift check pack, CloudFormation drift detection, IaC coverage, severity classification."""
from __future__ import annotations

import hashlib
from typing import List

__version__ = "0.1.0"
__all__ = ["__version__", "run_scan"]


def _fingerprint(pack: str, kind: str, resource_id: str) -> str:
    raw = f"{pack}|{kind}|{resource_id}"
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


def _extract_findings(scan_results: dict) -> list:
    """Extract canonical findings from drift scan results."""
    findings = []

    # Drifted stacks
    for item in scan_results.get("drift", {}).get("drifted_stacks", []):
        stack_name = item.get("stack_name", "unknown")
        fp = _fingerprint("drift", "stack-drifted", stack_name)
        drift_count = item.get("drifted_resources", 0)
        findings.append({
            "id": f"drift-stack-drifted-{fp}",
            "pack": "drift",
            "kind": "stack-drifted",
            "title": f"Stack '{stack_name}' has {drift_count} drifted resources",
            "severity": "high" if drift_count >= 3 else "medium",
            "confidence": 0.99,
            "effort": "medium",
            "risk": "medium",
            "resource_id": stack_name,
            "resource_arn": item.get("stack_arn", ""),
            "region": item.get("region", "us-east-1"),
            "description": f"CloudFormation stack has {drift_count} resources that differ from their template definition.",
            "recommended_action": f"aws cloudformation detect-stack-drift --stack-name {stack_name}",
            "estimated_monthly_impact": 0,
            "fingerprint": fp,
        })

    # Unmanaged resources (not in any IaC)
    for item in scan_results.get("coverage", {}).get("unmanaged", []):
        resource_id = item.get("resource_id", "unknown")
        fp = _fingerprint("drift", "unmanaged-resource", resource_id)
        findings.append({
            "id": f"drift-unmanaged-resource-{fp}",
            "pack": "drift",
            "kind": "unmanaged-resource",
            "title": f"{item.get('resource_type', 'Resource')} '{resource_id}' not managed by IaC",
            "severity": "low",
            "confidence": 0.80,
            "effort": "medium",
            "risk": "safe",
            "resource_id": resource_id,
            "resource_arn": item.get("resource_arn", ""),
            "region": item.get("region", "us-east-1"),
            "description": "This resource is not managed by CloudFormation or Terraform.",
            "recommended_action": "Import into IaC or document as intentionally unmanaged.",
            "estimated_monthly_impact": 0,
            "fingerprint": fp,
        })

    return findings


def run_scan(session, regions: List[str], *, quick: bool = False, deep: bool = False, **kwargs) -> dict:
    """Run the IaC drift + coverage scan and return a scored result dict."""
    from .scanner.cfn_drift import scan_cfn_drift
    from .scoring.engine import calculate_score

    if quick:
        regions = regions[:3]

    scan_results: dict = {}
    all_errors: list[str] = []

    if deep:
        try:
            drift_result, drift_errors = scan_cfn_drift(session, regions, timeout=120)
            scan_results["drift"] = drift_result
            all_errors.extend(drift_errors)
        except Exception as e:
            all_errors.append(f"Drift scan: {e}")

    if not quick:
        try:
            from .scanner.coverage import scan_coverage
            cov_result, cov_errors = scan_coverage(session, regions)
            scan_results["coverage"] = cov_result
            all_errors.extend(cov_errors)
        except Exception as e:
            all_errors.append(f"Coverage scan: {e}")

    scores = calculate_score(scan_results) if scan_results else {
        "overall_score": 100, "grade": "A+", "total_findings": 0,
        "severity_counts": {}, "breakdown": {},
    }

    findings = _extract_findings(scan_results)

    sev: dict = {"critical": 0, "high": 0, "medium": 0, "low": 0, "info": 0}
    for f in findings:
        s = f.get("severity", "info")
        if s in sev:
            sev[s] += 1

    return {
        "tool": "drift",
        "findings": findings,
        "scores": {
            "overall_score": int(scores.get("overall_score", 100)),
            "grade": scores.get("grade", "N/A"),
            "total_findings": len(findings),
            "severity_counts": {k: v for k, v in sev.items() if v > 0},
            "breakdown": scores.get("breakdown", {}),
        },
        "errors": all_errors,
    }
