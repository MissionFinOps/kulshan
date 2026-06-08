"""Estimated cost of insecurity, makes security tangible for finance."""

from typing import Dict, List
from ..scanner.base import Finding, Severity

# Industry benchmarks (IBM Cost of a Data Breach Report 2025, simplified)
BREACH_COST_PER_RECORD = 165  # USD average
AVG_RECORDS_PER_BUCKET = 100_000
AVG_RECORDS_PER_DB = 500_000

INCIDENT_BASE_COSTS = {
    "DATA-002": ("Public S3 bucket", AVG_RECORDS_PER_BUCKET * BREACH_COST_PER_RECORD),
    "DATA-005": ("Public RDS instance", AVG_RECORDS_PER_DB * BREACH_COST_PER_RECORD),
    "DATA-007": ("Public RDS snapshot", AVG_RECORDS_PER_DB * BREACH_COST_PER_RECORD * 0.5),
    "DATA-009": ("Public EBS snapshot", 2_000_000),
    "IAM-001": ("Root account compromise", 10_000_000),
    "IAM-005": ("Admin user compromise", 5_000_000),
    "IAM-006": ("Privilege escalation", 3_000_000),
    "IAM-007": ("Cross-account confused deputy", 4_000_000),
    "COMP-001": ("SSRF credential theft (IMDSv1)", 2_000_000),
    "COMP-003": ("Lambda secret exposure", 1_000_000),
    "NET-001": ("Full internet exposure", 3_000_000),
    "NET-003": ("Database port exposed", 5_000_000),
}


def estimate_breach_costs(findings: List[Finding]) -> Dict:
    """Estimate potential breach cost based on findings."""
    total_risk = 0
    top_risks = []

    seen_checks = set()
    for f in findings:
        if f.check_id in INCIDENT_BASE_COSTS and f.check_id not in seen_checks:
            label, cost = INCIDENT_BASE_COSTS[f.check_id]
            count = sum(1 for ff in findings if ff.check_id == f.check_id)
            # Diminishing returns for multiple instances
            estimated = cost * (1 + 0.3 * (count - 1))
            total_risk += estimated
            top_risks.append({
                "check_id": f.check_id,
                "label": label,
                "count": count,
                "estimated_cost": estimated,
            })
            seen_checks.add(f.check_id)

    top_risks.sort(key=lambda x: -x["estimated_cost"])

    return {
        "total_estimated_risk": total_risk,
        "top_risks": top_risks[:10],
        "methodology": "Based on IBM Cost of a Data Breach Report benchmarks. Estimates are illustrative, not predictive.",
    }
