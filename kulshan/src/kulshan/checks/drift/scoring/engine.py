"""Drift Health Scoring Engine (0-100)."""

from typing import Dict, List


def calculate_score(scan_results: Dict) -> Dict:
    """Calculate overall Drift Health Score."""
    drift_stats = scan_results.get("drift", {}).get("stats", {})
    cov_stats = scan_results.get("coverage", {}).get("stats", {})

    all_findings = []
    for key in scan_results:
        all_findings.extend(scan_results[key].get("findings", []))

    # --- Stack Drift: 30% ---
    checked = drift_stats.get("stacks_checked", 0)
    drifted = drift_stats.get("stacks_drifted", 0)
    if checked > 0:
        drift_pct = drifted / checked * 100
        stack_score = max(0, 100 - drift_pct * 2)
    else:
        stack_score = 50  # No stacks = uncertain
    stack_score = max(0, stack_score)

    # --- Resource Drift Severity: 25% ---
    sev = drift_stats.get("drift_by_severity", {})
    severity_score = 100.0
    severity_score -= min(50, sev.get("critical", 0) * 15)
    severity_score -= min(30, sev.get("moderate", 0) * 5)
    severity_score -= min(10, sev.get("cosmetic", 0) * 1)
    severity_score = max(0, severity_score)

    # --- Unmanaged Resources: 20% ---
    overall_pct = cov_stats.get("overall_pct", 0)
    unmanaged_score = min(100, overall_pct * 1.2)  # 83% coverage = 100 score
    unmanaged_score = max(0, unmanaged_score)

    # --- Drift Age: 15% (simplified, more drifted resources = likely older) ---
    total_drifted = len(drift_stats.get("drifted_resources", []))
    age_score = max(0, 100 - total_drifted * 5)

    # --- IaC Coverage: 10% ---
    coverage_score = min(100, overall_pct)

    # Weighted total
    overall = (
        stack_score * 0.30 +
        severity_score * 0.25 +
        unmanaged_score * 0.20 +
        age_score * 0.15 +
        coverage_score * 0.10
    )
    overall = max(0, min(100, overall))
    grade = _grade(overall)

    severity_counts = {"critical": 0, "high": 0, "medium": 0, "low": 0}
    for f in all_findings:
        severity_counts[f.get("severity", "medium")] = severity_counts.get(f.get("severity", "medium"), 0) + 1

    return {
        "overall_score": round(overall, 1),
        "grade": grade,
        "total_findings": len(all_findings),
        "severity_counts": severity_counts,
        "breakdown": {
            "stack_drift": {"score": round(stack_score, 1), "weight": "30%", "label": "Stack Drift"},
            "drift_severity": {"score": round(severity_score, 1), "weight": "25%", "label": "Drift Severity"},
            "unmanaged": {"score": round(unmanaged_score, 1), "weight": "20%", "label": "Unmanaged Resources"},
            "drift_age": {"score": round(age_score, 1), "weight": "15%", "label": "Drift Volume"},
            "iac_coverage": {"score": round(coverage_score, 1), "weight": "10%", "label": "IaC Coverage"},
        },
        "drift_summary": {
            "stacks_checked": checked,
            "stacks_drifted": drifted,
            "stacks_in_sync": drift_stats.get("stacks_in_sync", 0),
            "total_drifted_resources": total_drifted,
            "critical_drifts": sev.get("critical", 0),
            "moderate_drifts": sev.get("moderate", 0),
            "cosmetic_drifts": sev.get("cosmetic", 0),
        },
        "coverage": cov_stats.get("coverage", {}),
        "coverage_pct": overall_pct,
        "drifted_resources": drift_stats.get("drifted_resources", []),
        "findings": all_findings,
    }


def _grade(score):
    if score >= 95: return "A+"
    if score >= 90: return "A"
    if score >= 85: return "A-"
    if score >= 80: return "B+"
    if score >= 75: return "B"
    if score >= 70: return "B-"
    if score >= 65: return "C+"
    if score >= 60: return "C"
    if score >= 55: return "C-"
    if score >= 45: return "D"
    return "F"


def grade_color(grade):
    if grade.startswith("A"): return "green"
    if grade.startswith("B"): return "yellow"
    if grade.startswith("C"): return "dark_orange"
    return "red"
