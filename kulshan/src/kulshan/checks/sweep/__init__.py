"""Sweep check pack, orphans, zombies, monthly waste, account hygiene scoring."""

from __future__ import annotations

import hashlib
import re
from typing import List

__version__ = "0.1.0"
__all__ = ["__version__", "run_scan"]


def _fingerprint(pack: str, kind: str, resource_id: str) -> str:
    raw = f"{pack}|{kind}|{resource_id}"
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


def _orphan_to_finding(orphan: dict) -> dict:
    """Convert a sweep orphan dict to a canonical finding."""
    resource_id = orphan.get("resource_id", "unknown")
    resource_type = orphan.get("resource_type", "Unknown")
    monthly_cost = None
    confidence_str = orphan.get("confidence", "medium")
    region = orphan.get("region", "us-east-1")
    reason = orphan.get("reason", "Orphaned resource")

    # Map resource_type to kind
    kind_map = {
        "EBS Volume": "unused-ebs-volume",
        "Elastic IP": "unused-elastic-ip",
        "EBS Snapshot": "orphaned-snapshot",
        "AMI": "stale-ami",
        "Network Interface": "unused-eni",
        "NAT Gateway": "unused-nat-gateway",
        "Load Balancer": "idle-load-balancer",
        "RDS Instance": "stopped-instance",
        "Security Group": "unused-security-group",
        "S3 Bucket": "empty-bucket",
    }
    kind = kind_map.get(resource_type, "orphaned-resource")

    confidence_map = {"high": 0.95, "medium": 0.70, "low": 0.40}
    confidence = confidence_map.get(confidence_str, 0.70)
    if orphan.get("status") in {"insufficient_evidence", "could_not_check"}:
        confidence = 0.0

    fp = _fingerprint("sweep", kind, resource_id)
    return {
        "id": f"sweep-{kind}-{fp}",
        "pack": "sweep",
        "kind": kind,
        "title": f"{resource_type} '{resource_id}': {orphan.get('status', 'review_candidate')}",
        "severity": "info"
        if orphan.get("status") in {"insufficient_evidence", "could_not_check"}
        else "low",
        "confidence": confidence,
        "effort": "medium",
        "risk": "medium",
        "resource_id": resource_id,
        "resource_arn": orphan.get("resource_arn", ""),
        "region": region,
        "description": reason,
        "recommended_action": orphan.get(
            "next_step", "Review owner, usage and recovery dependencies before any change."
        ),
        "evidence": {
            **orphan.get("evidence", {}),
            "resource_id": resource_id,
            "resource_type": resource_type,
            "region": region,
            "finding_status": orphan.get("status", "review_candidate"),
            "confidence_scope": "Confidence in the reported observation, not removal safety",
            "financial": orphan.get(
                "financial", {"semantics": "unknown", "value": None, "currency": None}
            ),
            "cleanup_reference": orphan.get("cleanup_action", ""),
            "next_step": orphan.get("next_step", "Review owner, usage and recovery dependencies."),
        },
        "estimated_monthly_impact": monthly_cost,
        "fingerprint": fp,
        "metadata": {
            "resource_type": resource_type,
            "age_days": orphan.get("age_days"),
            "tags": orphan.get("tags", {}),
        },
    }


def run_scan(session, regions: List[str], *, quick: bool = False, **kwargs) -> dict:
    """Run the orphan/waste scan and return a scored result dict."""
    from .scanner.compute import scan_compute
    from .scanner.network import scan_network
    from .scanner.storage import scan_storage
    from .scanner.database import scan_database
    from .scanner.monitoring import scan_monitoring
    from .scoring.engine import calculate_score
    from kulshan.parallel import parallel_scanners
    from .scanner.evidence import attributable_billing
    from kulshan.coverage import CoverageError, ExecutionRecord

    if quick:
        regions = regions[:3]

    all_orphans: list = []
    all_errors: list[str] = []

    # Run all scanners in parallel
    scanners = {
        "compute": scan_compute,
        "network": scan_network,
        "storage": scan_storage,
        "database": scan_database,
        "monitoring": scan_monitoring,
    }

    execution_records = []

    def coverage_error(name, error):
        match = re.search(r"describe_\w+|list_\w+|GetMetricStatistics", str(error))
        action = match.group() if match else "scanner"
        if action == "GetMetricStatistics":
            service = "cloudwatch"
        elif name == "network":
            service = "elbv2" if "target" in action or "load_balancer" in action else "ec2"
        elif name == "monitoring":
            service = (
                "logs"
                if "log_group" in action
                else ("lambda" if "function" in action else "cloudwatch")
            )
        elif name == "database":
            service = "rds"
        elif name == "storage":
            service = "s3" if "bucket" in action or "objects" in action else "ecr"
        else:
            service = "ec2"
        return CoverageError(
            service=service, action=action, code="EvidenceUnavailable", message=str(error)
        )

    def tracked(name, scanner):
        def execute(session, regions):
            findings, errors = [], []
            for index, region in enumerate(regions):
                try:
                    extra = {"include_global": index == 0} if name == "storage" else {}
                    observed, regional_errors = scanner(session, [region], **extra)
                except Exception as exc:
                    observed, regional_errors = [], [f"{name} ({region}): {exc}"]
                findings.extend(observed)
                errors.extend(regional_errors)
                execution_records.append(
                    {
                        **ExecutionRecord(
                            pack="sweep",
                            region=region,
                            check=name,
                            status="partial" if regional_errors else "complete",
                            findings_count=len(observed),
                            errors=[coverage_error(name, e) for e in regional_errors],
                        ).to_dict(),
                        "scanner": name,
                    }
                )
            return findings, errors

        return execute

    results, errors = parallel_scanners(
        {name: tracked(name, scanner) for name, scanner in scanners.items()}, session, regions
    )
    all_errors.extend(errors)

    for scanner_result in results.values():
        if isinstance(scanner_result, list):
            all_orphans.extend(scanner_result)

    scores = calculate_score(
        all_orphans, complete=not all_errors and len(results) == len(scanners) and bool(regions)
    )

    for orphan in all_orphans:
        supplied = kwargs.get("financial_evidence") or {}
        orphan["financial"] = attributable_billing(
            orphan, supplied.get((orphan["region"], orphan["resource_id"]))
        )

    # Convert orphans to canonical findings
    findings = [_orphan_to_finding(o) for o in all_orphans]

    sev: dict = {"critical": 0, "high": 0, "medium": 0, "low": 0, "info": 0}
    for f in findings:
        s = f.get("severity", "info")
        if s in sev:
            sev[s] += 1

    return {
        "tool": "sweep",
        "findings": findings,
        "scores": {
            "overall_score": scores["overall_score"],
            "grade": scores.get("grade", "A+"),
            "total_findings": len(findings),
            "severity_counts": {k: v for k, v in sev.items() if v > 0},
            "breakdown": scores.get("breakdown", {}),
            "monthly_waste": scores["total_monthly_waste"],
            "unknown_financial_impact_count": len(all_orphans),
        },
        "coverage": sorted(execution_records, key=lambda e: (e["scanner"], e["region"])),
        "errors": all_errors,
        "partial": scores["overall_score"] is None,
        "completeness": "partial" if scores["overall_score"] is None else "complete",
    }
