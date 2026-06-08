"""Tag Compliance Scoring Engine (0-100)."""


def calculate_score(compliance, consistency, cost_impact):
    """Calculate overall Tag Compliance Score."""
    # Required Tag Coverage: 35%
    tag_coverage = compliance.get("compliance_pct", 0)
    tag_coverage_score = min(100, tag_coverage)

    # Tag Value Consistency: 20%
    consistency_scores = []
    for key, data in consistency.items():
        if data["chaos_level"] == "Low":
            consistency_scores.append(100)
        elif data["chaos_level"] == "Medium":
            consistency_scores.append(60)
        else:
            consistency_scores.append(20)
    consistency_score = sum(consistency_scores) / len(consistency_scores) if consistency_scores else 100

    # Resource Coverage: 20%
    total = compliance.get("total_resources", 0)
    untagged = compliance.get("untagged", 0)
    resource_coverage = ((total - untagged) / total * 100) if total > 0 else 100

    # Tag Key Hygiene: 15%
    # Penalize for clusters (similar values that should be standardized)
    total_fixable = sum(
        sum(c["fixable"] for c in data.get("clusters", []))
        for data in consistency.values()
    )
    hygiene_score = max(0, 100 - total_fixable * 2)

    # Cost Attribution: 10%
    dark_pct = cost_impact.get("dark_money_pct", 0)
    cost_score = max(0, 100 - dark_pct)

    # Weighted total
    overall = (
        tag_coverage_score * 0.35 +
        consistency_score * 0.20 +
        resource_coverage * 0.20 +
        hygiene_score * 0.15 +
        cost_score * 0.10
    )

    overall = max(0, min(100, overall))

    grade = _grade(overall)

    return {
        "overall_score": round(overall, 1),
        "grade": grade,
        "breakdown": {
            "tag_coverage": {"score": round(tag_coverage_score, 1), "weight": "35%"},
            "consistency": {"score": round(consistency_score, 1), "weight": "20%"},
            "resource_coverage": {"score": round(resource_coverage, 1), "weight": "20%"},
            "hygiene": {"score": round(hygiene_score, 1), "weight": "15%"},
            "cost_attribution": {"score": round(cost_score, 1), "weight": "10%"},
        },
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
