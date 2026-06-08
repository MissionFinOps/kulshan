"""Account Hygiene Scoring Engine (0-100)."""

from typing import Dict, List
from datetime import datetime, timezone


def calculate_score(orphans: List[Dict]) -> Dict:
    """Calculate overall Account Hygiene Score based on orphan findings."""
    categories = {
        "compute": {"weight": 0.25, "orphans": [], "label": "Compute Hygiene"},
        "network": {"weight": 0.20, "orphans": [], "label": "Network Hygiene"},
        "storage": {"weight": 0.20, "orphans": [], "label": "Storage Hygiene"},
        "database": {"weight": 0.15, "orphans": [], "label": "Database Hygiene"},
        "monitoring": {"weight": 0.10, "orphans": [], "label": "Monitoring Hygiene"},
    }
    age_weight = 0.10

    for o in orphans:
        cat = o.get("category", "compute")
        if cat in categories:
            categories[cat]["orphans"].append(o)

    # Score each category: fewer orphans + lower cost = higher score
    cat_scores = {}
    for cat, data in categories.items():
        items = data["orphans"]
        if not items:
            cat_scores[cat] = 100.0
            continue

        # Penalty based on count (diminishing returns)
        count = len(items)
        count_penalty = min(60, count * 3)  # Max 60 points lost from count

        # Penalty based on monthly cost
        total_cost = sum(o.get("monthly_cost", 0) for o in items)
        cost_penalty = min(30, total_cost / 50)  # $50/mo = 1 point, max 30

        # Penalty for high-confidence orphans
        high_conf = sum(1 for o in items if o.get("confidence") == "high")
        conf_penalty = min(10, high_conf * 2)

        score = max(0, 100 - count_penalty - cost_penalty - conf_penalty)
        cat_scores[cat] = round(score, 1)

    # Age factor: penalize for very old orphans
    old_orphans = [o for o in orphans if (o.get("age_days") or 0) > 180]
    age_score = max(0, 100 - len(old_orphans) * 5)

    # Weighted total
    overall = sum(cat_scores[cat] * categories[cat]["weight"] for cat in categories)
    overall += age_score * age_weight
    overall = max(0, min(100, overall))

    grade = _grade(overall)

    # Monthly waste total
    total_monthly_waste = sum(o.get("monthly_cost", 0) for o in orphans)
    annual_waste = total_monthly_waste * 12

    # Top offenders by cost
    by_type = {}
    for o in orphans:
        rtype = o["resource_type"]
        if rtype not in by_type:
            by_type[rtype] = {"count": 0, "monthly_cost": 0}
        by_type[rtype]["count"] += 1
        by_type[rtype]["monthly_cost"] += o.get("monthly_cost", 0)
    top_offenders = sorted(by_type.items(), key=lambda x: x[1]["monthly_cost"], reverse=True)

    # Oldest orphan
    oldest = None
    for o in orphans:
        age = o.get("age_days")
        if age and (oldest is None or age > oldest.get("age_days", 0)):
            oldest = o

    return {
        "overall_score": round(overall, 1),
        "grade": grade,
        "total_orphans": len(orphans),
        "total_monthly_waste": round(total_monthly_waste, 2),
        "annual_waste": round(annual_waste, 2),
        "breakdown": {
            cat: {
                "score": cat_scores[cat],
                "weight": f"{int(data['weight'] * 100)}%",
                "label": data["label"],
                "count": len(data["orphans"]),
                "monthly_cost": round(sum(o.get("monthly_cost", 0) for o in data["orphans"]), 2),
            }
            for cat, data in categories.items()
        },
        "age_factor": {"score": round(age_score, 1), "weight": "10%", "old_count": len(old_orphans)},
        "top_offenders": top_offenders[:10],
        "oldest_orphan": oldest,
        "by_confidence": {
            "high": len([o for o in orphans if o.get("confidence") == "high"]),
            "medium": len([o for o in orphans if o.get("confidence") == "medium"]),
            "low": len([o for o in orphans if o.get("confidence") == "low"]),
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
