"""Tag compliance analysis, check resources against required tags."""

from typing import Dict, List
from collections import defaultdict

DEFAULT_REQUIRED_TAGS = ["Name", "Environment", "Owner", "CostCenter"]


def analyze_compliance(resources, required_tags=None):
    """Analyze tag compliance across all resources."""
    if required_tags is None:
        required_tags = DEFAULT_REQUIRED_TAGS

    total = len(resources)
    if total == 0:
        return {"score": 100, "total_resources": 0, "compliant": 0, "violations": []}

    compliant = 0
    partially_compliant = 0
    non_compliant = 0
    untagged = 0
    violations = []
    by_service = defaultdict(lambda: {"total": 0, "compliant": 0, "untagged": 0})
    by_tag = {tag: {"present": 0, "missing": 0} for tag in required_tags}

    for r in resources:
        tags = r.get("tags", {})
        service = r.get("service", "unknown")
        by_service[service]["total"] += 1

        if not tags:
            untagged += 1
            non_compliant += 1
            by_service[service]["untagged"] += 1
            for tag in required_tags:
                by_tag[tag]["missing"] += 1
            violations.append({
                "arn": r["arn"], "resource_type": r["resource_type"],
                "region": r["region"], "issue": "No tags at all",
                "missing_tags": required_tags,
            })
            continue

        missing = [t for t in required_tags if t not in tags]
        if not missing:
            compliant += 1
            by_service[service]["compliant"] += 1
            for tag in required_tags:
                by_tag[tag]["present"] += 1
        elif len(missing) < len(required_tags):
            partially_compliant += 1
            for tag in required_tags:
                if tag in tags:
                    by_tag[tag]["present"] += 1
                else:
                    by_tag[tag]["missing"] += 1
            violations.append({
                "arn": r["arn"], "resource_type": r["resource_type"],
                "region": r["region"], "issue": f"Missing {len(missing)} required tag(s)",
                "missing_tags": missing,
            })
        else:
            non_compliant += 1
            for tag in required_tags:
                by_tag[tag]["missing"] += 1
            violations.append({
                "arn": r["arn"], "resource_type": r["resource_type"],
                "region": r["region"], "issue": f"Missing all {len(required_tags)} required tags",
                "missing_tags": missing,
            })

    compliance_pct = (compliant / total * 100) if total else 0

    return {
        "total_resources": total,
        "compliant": compliant,
        "partially_compliant": partially_compliant,
        "non_compliant": non_compliant,
        "untagged": untagged,
        "compliance_pct": compliance_pct,
        "required_tags": required_tags,
        "by_service": dict(by_service),
        "by_tag": by_tag,
        "violations": violations,
    }
