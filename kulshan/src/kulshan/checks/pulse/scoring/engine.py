"""Observability Maturity Scoring Engine (0-100)."""

from typing import Dict, List


def calculate_score(scan_results: Dict) -> Dict:
    """Calculate overall Observability Maturity Score."""
    log_stats = scan_results.get("logging", {}).get("stats", {})
    alarm_stats = scan_results.get("alarms", {}).get("stats", {})
    trace_stats = scan_results.get("tracing", {}).get("stats", {})

    all_findings = []
    for key in scan_results:
        all_findings.extend(scan_results[key].get("findings", []))

    # --- Log Coverage: 25% ---
    log_score = 100.0
    if not log_stats.get("cloudtrail_enabled"):
        log_score -= 40
    if not log_stats.get("cloudtrail_multi_region"):
        log_score -= 10

    vpc_total = log_stats.get("vpc_flow_logs", {}).get("total_vpcs", 0)
    vpc_flow = log_stats.get("vpc_flow_logs", {}).get("with_flow_logs", 0)
    if vpc_total > 0:
        vpc_pct = vpc_flow / vpc_total * 100
        log_score -= max(0, (100 - vpc_pct) * 0.2)

    s3_total = log_stats.get("s3_access_logging", {}).get("total_buckets", 0)
    s3_log = log_stats.get("s3_access_logging", {}).get("with_logging", 0)
    if s3_total > 0:
        s3_pct = s3_log / s3_total * 100
        log_score -= max(0, (100 - s3_pct) * 0.1)

    no_retention = log_stats.get("log_groups_no_retention", 0)
    log_score -= min(10, no_retention * 0.5)
    log_score = max(0, log_score)

    # --- Alarm Coverage: 25% ---
    alarm_score = 100.0
    if alarm_stats.get("total_alarms", 0) == 0:
        alarm_score = 0
    else:
        blind_spots = alarm_stats.get("blind_spots", {})
        total_resources = sum(bs["total"] for bs in blind_spots.values())
        monitored = sum(bs["monitored"] for bs in blind_spots.values())
        if total_resources > 0:
            coverage_pct = monitored / total_resources * 100
            alarm_score = coverage_pct

        no_action = alarm_stats.get("alarms_without_actions", 0)
        alarm_score -= min(20, no_action * 2)

        insufficient = alarm_stats.get("alarms_insufficient", 0)
        alarm_score -= min(10, insufficient)
    alarm_score = max(0, alarm_score)

    # --- Metric Coverage: 20% (derived from alarm blind spots) ---
    metric_score = 100.0
    blind_spots = alarm_stats.get("blind_spots", {})
    for rtype, bs in blind_spots.items():
        if bs["total"] > 0:
            gap_pct = bs["unmonitored"] / bs["total"] * 100
            metric_score -= gap_pct * 0.15
    metric_score = max(0, metric_score)

    # --- Tracing Adoption: 15% ---
    trace_score = 100.0
    if trace_stats.get("config_enabled_regions", 0) == 0:
        trace_score -= 30

    ecs_total = trace_stats.get("ecs_clusters", {}).get("total", 0)
    ecs_insights = trace_stats.get("ecs_clusters", {}).get("with_insights", 0)
    if ecs_total > 0 and ecs_insights < ecs_total:
        trace_score -= 15

    eks_total = trace_stats.get("eks_clusters", {}).get("total", 0)
    eks_log = trace_stats.get("eks_clusters", {}).get("with_logging", 0)
    if eks_total > 0 and eks_log < eks_total:
        trace_score -= 15

    lam_total = trace_stats.get("lambda_tracing", {}).get("total", 0)
    lam_xray = trace_stats.get("lambda_tracing", {}).get("with_xray", 0)
    if lam_total > 0 and lam_xray == 0:
        trace_score -= 20
    trace_score = max(0, trace_score)

    # --- Centralization: 15% ---
    central_score = 100.0
    if not log_stats.get("cloudtrail_enabled"):
        central_score -= 30
    if alarm_stats.get("sns_topics", 0) == 0:
        central_score -= 30
    rds_total = log_stats.get("rds_logging", {}).get("total", 0)
    rds_enhanced = log_stats.get("rds_logging", {}).get("with_enhanced", 0)
    if rds_total > 0 and rds_enhanced < rds_total:
        central_score -= 20
    central_score = max(0, central_score)

    # Weighted total
    overall = (
        log_score * 0.25 +
        alarm_score * 0.25 +
        metric_score * 0.20 +
        trace_score * 0.15 +
        central_score * 0.15
    )
    overall = max(0, min(100, overall))
    grade = _grade(overall)

    severity_counts = {"critical": 0, "high": 0, "medium": 0, "low": 0}
    for f in all_findings:
        sev = f.get("severity", "medium")
        severity_counts[sev] = severity_counts.get(sev, 0) + 1

    return {
        "overall_score": round(overall, 1),
        "grade": grade,
        "total_findings": len(all_findings),
        "severity_counts": severity_counts,
        "breakdown": {
            "log_coverage": {"score": round(log_score, 1), "weight": "25%", "label": "Log Coverage"},
            "alarm_coverage": {"score": round(alarm_score, 1), "weight": "25%", "label": "Alarm Coverage"},
            "metric_coverage": {"score": round(metric_score, 1), "weight": "20%", "label": "Metric Coverage"},
            "tracing": {"score": round(trace_score, 1), "weight": "15%", "label": "Tracing & Config"},
            "centralization": {"score": round(central_score, 1), "weight": "15%", "label": "Centralization"},
        },
        "blind_spots": alarm_stats.get("blind_spots", {}),
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
