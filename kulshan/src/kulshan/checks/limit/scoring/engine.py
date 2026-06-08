"""Quota Headroom Scoring Engine (0-100)."""

from typing import Dict, List


def calculate_score(quotas: List[Dict]) -> Dict:
    """Calculate overall Quota Headroom Score."""
    # Categorize quotas by utilization
    critical = []   # >= 80%
    warning = []    # >= 60%
    healthy = []    # < 60%
    unknown = []    # no usage data

    for q in quotas:
        pct = q.get("utilization_pct")
        if pct is None:
            unknown.append(q)
        elif pct >= 80:
            critical.append(q)
        elif pct >= 60:
            warning.append(q)
        else:
            healthy.append(q)

    total_with_data = len(critical) + len(warning) + len(healthy)

    # --- Critical Limits: 40% ---
    if total_with_data > 0:
        critical_pct = len(critical) / total_with_data * 100
        critical_score = max(0, 100 - critical_pct * 5)  # Each 1% critical = -5 points
    else:
        critical_score = 50  # No data = uncertain

    # Extra penalty for anything above 90%
    above_90 = [q for q in critical if (q.get("utilization_pct") or 0) >= 90]
    critical_score -= len(above_90) * 10
    critical_score = max(0, critical_score)

    # --- Growth Trajectory: 25% (simplified, based on current headroom) ---
    # Without historical data, we estimate based on how close things are
    if total_with_data > 0:
        avg_util = sum(q.get("utilization_pct", 0) for q in critical + warning + healthy) / total_with_data
        growth_score = max(0, 100 - avg_util)
    else:
        growth_score = 50

    # --- Breadth of Monitoring: 20% ---
    total_quotas = len(quotas)
    with_usage = total_with_data
    if total_quotas > 0:
        monitoring_pct = with_usage / total_quotas * 100
        breadth_score = min(100, monitoring_pct * 1.5)  # Reward having usage data
    else:
        breadth_score = 0

    # --- Adjustability: 15% ---
    adjustable_critical = [q for q in critical if q.get("adjustable")]
    if critical:
        adj_pct = len(adjustable_critical) / len(critical) * 100
        adjust_score = adj_pct  # Higher = better (can request increases)
    else:
        adjust_score = 100  # No critical = full score

    # Weighted total
    overall = (
        critical_score * 0.40 +
        growth_score * 0.25 +
        breadth_score * 0.20 +
        adjust_score * 0.15
    )
    overall = max(0, min(100, overall))
    grade = _grade(overall)

    # Top concerns (sorted by utilization)
    top_concerns = sorted(
        [q for q in quotas if q.get("utilization_pct") is not None],
        key=lambda q: q["utilization_pct"], reverse=True
    )[:20]

    return {
        "overall_score": round(overall, 1),
        "grade": grade,
        "total_quotas_checked": total_quotas,
        "with_usage_data": with_usage,
        "breakdown": {
            "critical_limits": {"score": round(critical_score, 1), "weight": "40%", "label": "Critical Limits"},
            "growth_trajectory": {"score": round(growth_score, 1), "weight": "25%", "label": "Growth Trajectory"},
            "monitoring_breadth": {"score": round(breadth_score, 1), "weight": "20%", "label": "Monitoring Breadth"},
            "adjustability": {"score": round(adjust_score, 1), "weight": "15%", "label": "Adjustability"},
        },
        "counts": {
            "critical": len(critical),
            "warning": len(warning),
            "healthy": len(healthy),
            "unknown": len(unknown),
        },
        "top_concerns": top_concerns,
        "above_90": above_90,
    }


def plan_scaling(quotas: List[Dict], scale_factor: float) -> List[Dict]:
    """Identify quotas that would be breached at a given scale factor."""
    blockers = []
    for q in quotas:
        usage = q.get("current_usage")
        limit = q.get("quota_value")
        if usage is not None and limit and limit > 0:
            projected = usage * scale_factor
            if projected > limit:
                blockers.append({
                    **q,
                    "projected_usage": round(projected, 1),
                    "overage": round(projected - limit, 1),
                    "increase_needed": round(projected * 1.2, 0),  # 20% buffer
                })
    return sorted(blockers, key=lambda b: b["overage"], reverse=True)


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
