"""Freshness Scoring Engine (0-100)."""
from typing import Dict, List

def calculate_score(scan_results: Dict) -> Dict:
    aging = scan_results.get("aging", [])
    stats = scan_results.get("stats", {})

    by_cat = {"runtime": [], "engine": [], "instance_age": [], "certificate": [], "storage_modernization": []}
    for a in aging:
        cat = a.get("category", "runtime")
        if cat in by_cat: by_cat[cat].append(a)

    # Runtime Freshness: 25%
    rt_items = by_cat["runtime"]
    rt_crit = len([a for a in rt_items if a["severity"] == "critical"])
    rt_warn = len([a for a in rt_items if a["severity"] == "warning"])
    rt_score = max(0, 100 - rt_crit * 15 - rt_warn * 5)

    # Engine Freshness: 25%
    eng_items = by_cat["engine"]
    eng_crit = len([a for a in eng_items if a["severity"] == "critical"])
    eng_warn = len([a for a in eng_items if a["severity"] == "warning"])
    eng_score = max(0, 100 - eng_crit * 20 - eng_warn * 8)

    # Instance Freshness: 20%
    inst_items = by_cat["instance_age"]
    inst_crit = len([a for a in inst_items if a["severity"] == "critical"])
    inst_warn = len([a for a in inst_items if a["severity"] == "warning"])
    inst_score = max(0, 100 - inst_crit * 10 - inst_warn * 3)

    # Certificate Health: 15%
    cert_items = by_cat["certificate"]
    cert_crit = len([a for a in cert_items if a["severity"] == "critical"])
    cert_warn = len([a for a in cert_items if a["severity"] == "warning"])
    cert_score = max(0, 100 - cert_crit * 25 - cert_warn * 10)

    # Storage Modernization: 15%
    gp2_count = len(by_cat["storage_modernization"])
    stor_score = max(0, 100 - gp2_count * 2)

    overall = rt_score*0.25 + eng_score*0.25 + inst_score*0.20 + cert_score*0.15 + stor_score*0.15
    overall = max(0, min(100, overall))
    grade = _grade(overall)

    staleness_tax = sum(abs(a.get("monthly_cost_impact", 0)) for a in aging if a.get("monthly_cost_impact", 0) != 0)
    sev_counts = {"critical": len([a for a in aging if a["severity"]=="critical"]),
                  "warning": len([a for a in aging if a["severity"]=="warning"]),
                  "modernize": len([a for a in aging if a["severity"]=="modernize"])}

    return {"overall_score": round(overall,1), "grade": grade, "total_aging": len(aging),
            "severity_counts": sev_counts, "staleness_tax_monthly": round(staleness_tax,2),
            "breakdown": {
                "runtime": {"score": round(rt_score,1), "weight": "25%", "label": "Runtime Freshness"},
                "engine": {"score": round(eng_score,1), "weight": "25%", "label": "Engine Freshness"},
                "instance": {"score": round(inst_score,1), "weight": "20%", "label": "Instance Freshness"},
                "certificate": {"score": round(cert_score,1), "weight": "15%", "label": "Certificate Health"},
                "storage": {"score": round(stor_score,1), "weight": "15%", "label": "Storage Modernization"},
            }, "aging": aging, "stats": stats}


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
