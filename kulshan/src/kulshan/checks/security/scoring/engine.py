"""Security posture scoring engine."""

from typing import Dict, List
from ..scanner.base import Finding, Severity

CATEGORY_WEIGHTS = {
    "Identity & Access": 0.25,
    "Network Exposure": 0.20,
    "Data Protection": 0.20,
    "Compute Security": 0.15,
    "Logging & Monitoring": 0.10,
    "Encryption & Secrets": 0.10,
}

SEVERITY_PENALTY = {
    Severity.CRITICAL: 15,
    Severity.HIGH: 8,
    Severity.MEDIUM: 3,
    Severity.LOW: 1,
    Severity.INFO: 0,
}


def grade_from_score(score: float) -> str:
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


def grade_color(grade: str) -> str:
    if grade.startswith("A"): return "green"
    if grade.startswith("B"): return "yellow"
    if grade.startswith("C"): return "dark_orange"
    return "red"


def calculate_scores(findings: List[Finding]) -> Dict:
    """Calculate overall and per-category security scores."""
    category_findings: Dict[str, List[Finding]] = {}
    for cat in CATEGORY_WEIGHTS:
        category_findings[cat] = []
    for f in findings:
        if f.category in category_findings:
            category_findings[f.category].append(f)

    category_scores = {}
    for cat, weight in CATEGORY_WEIGHTS.items():
        penalty = sum(SEVERITY_PENALTY.get(f.severity, 0) for f in category_findings[cat])
        score = max(0, min(100, 100 - penalty))
        category_scores[cat] = {
            "score": score,
            "grade": grade_from_score(score),
            "weight": weight,
            "findings": len(category_findings[cat]),
            "critical": sum(1 for f in category_findings[cat] if f.severity == Severity.CRITICAL),
            "high": sum(1 for f in category_findings[cat] if f.severity == Severity.HIGH),
            "medium": sum(1 for f in category_findings[cat] if f.severity == Severity.MEDIUM),
            "low": sum(1 for f in category_findings[cat] if f.severity == Severity.LOW),
        }

    overall = sum(category_scores[c]["score"] * CATEGORY_WEIGHTS[c] for c in CATEGORY_WEIGHTS)
    overall = max(0, min(100, overall))

    severity_counts = {
        "critical": sum(1 for f in findings if f.severity == Severity.CRITICAL),
        "high": sum(1 for f in findings if f.severity == Severity.HIGH),
        "medium": sum(1 for f in findings if f.severity == Severity.MEDIUM),
        "low": sum(1 for f in findings if f.severity == Severity.LOW),
    }

    return {
        "overall_score": round(overall, 1),
        "overall_grade": grade_from_score(overall),
        "category_scores": category_scores,
        "total_findings": len(findings),
        "severity_counts": severity_counts,
    }
