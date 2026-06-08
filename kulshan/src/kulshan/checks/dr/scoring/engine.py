"""DR Readiness Scoring Engine (0-100)."""

from typing import Dict, List


def calculate_score(scan_results: Dict) -> Dict:
    """Calculate overall DR Readiness Score from all scanner results."""
    backup = scan_results.get("backup", {}).get("stats", {})
    compute = scan_results.get("compute", {}).get("stats", {})
    database = scan_results.get("database", {}).get("stats", {})
    storage = scan_results.get("storage", {}).get("stats", {})
    dns = scan_results.get("dns", {}).get("stats", {})
    spofs = scan_results.get("spof", {}).get("spofs", [])

    all_findings = []
    for key in scan_results:
        all_findings.extend(scan_results[key].get("findings", []))

    # --- Backup Coverage: 25% ---
    backup_score = 100.0
    if backup.get("backup_plans", 0) == 0:
        backup_score -= 50
    if backup.get("protected_resources", 0) == 0:
        backup_score -= 30
    stale = len(backup.get("stale_recovery_points", []))
    backup_score -= min(20, stale * 2)
    backup_score = max(0, backup_score)

    # --- Multi-AZ Deployment: 20% ---
    multiaz_score = 100.0
    # Penalize for single-AZ instances
    if compute.get("instances", 0) > 0 and not compute.get("multi_az_instances", False):
        multiaz_score -= 40
    # Penalize for SPOF ASGs
    spof_asg_count = len(compute.get("spof_asgs", []))
    multiaz_score -= min(30, spof_asg_count * 10)
    # Penalize for single-AZ LBs
    single_az_lb = len(compute.get("single_az_lbs", []))
    multiaz_score -= min(20, single_az_lb * 10)
    # Penalize for RDS not multi-AZ
    rds_no_maz = len(database.get("rds_no_multi_az", []))
    multiaz_score -= min(30, rds_no_maz * 10)
    multiaz_score = max(0, multiaz_score)

    # --- Data Durability: 20% ---
    data_score = 100.0
    # RDS with no backups
    rds_no_backup = len(database.get("rds_no_backup", []))
    data_score -= min(40, rds_no_backup * 15)
    # RDS short retention
    rds_short = len(database.get("rds_short_retention", []))
    data_score -= min(15, rds_short * 5)
    # S3 no versioning
    total_buckets = len(storage.get("buckets", []))
    no_ver = len(storage.get("no_versioning", []))
    if total_buckets > 0:
        no_ver_pct = no_ver / total_buckets * 100
        data_score -= min(25, no_ver_pct * 0.25)
    # DynamoDB no PITR
    ddb_no_pitr = len(database.get("dynamodb_no_pitr", []))
    data_score -= min(20, ddb_no_pitr * 5)
    data_score = max(0, data_score)

    # --- Failover Readiness: 15% ---
    failover_score = 100.0
    if dns.get("hosted_zones", 0) > 0:
        if dns.get("health_checks", 0) == 0:
            failover_score -= 40
        if dns.get("failover_records", 0) == 0:
            failover_score -= 30
        no_hc_zones = len(dns.get("zones_without_health_checks", []))
        failover_score -= min(20, no_hc_zones * 10)
    # ElastiCache no failover
    ec_no_fo = len(database.get("elasticache_no_failover", []))
    failover_score -= min(20, ec_no_fo * 10)
    failover_score = max(0, failover_score)

    # --- Recovery Freshness: 10% ---
    freshness_score = 100.0
    freshest = backup.get("freshest_by_resource", {})
    if freshest:
        ages = [v["age_hours"] for v in freshest.values()]
        avg_age = sum(ages) / len(ages) if ages else 0
        if avg_age > 168:  # > 7 days
            freshness_score -= 50
        elif avg_age > 48:  # > 2 days
            freshness_score -= 25
        elif avg_age > 24:
            freshness_score -= 10
    elif backup.get("backup_plans", 0) == 0:
        freshness_score = 0  # No backups at all
    freshness_score = max(0, freshness_score)

    # --- Cross-Region Posture: 10% ---
    cross_region_score = 100.0
    if storage.get("cross_region_replication", 0) == 0 and total_buckets > 0:
        cross_region_score -= 40
    # No cross-region read replicas (simplified check)
    total_rds = len(database.get("rds_instances", []))
    if total_rds > 0:
        has_replicas = any(r.get("read_replicas", 0) > 0 for r in database.get("rds_instances", []))
        if not has_replicas:
            cross_region_score -= 30
    # SPOFs penalty
    cross_region_score -= min(30, len(spofs) * 5)
    cross_region_score = max(0, cross_region_score)

    # Weighted total
    overall = (
        backup_score * 0.25 +
        multiaz_score * 0.20 +
        data_score * 0.20 +
        failover_score * 0.15 +
        freshness_score * 0.10 +
        cross_region_score * 0.10
    )
    overall = max(0, min(100, overall))
    grade = _grade(overall)

    # Severity counts
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
            "backup_coverage": {"score": round(backup_score, 1), "weight": "25%", "label": "Backup Coverage"},
            "multi_az": {"score": round(multiaz_score, 1), "weight": "20%", "label": "Multi-AZ Deployment"},
            "data_durability": {"score": round(data_score, 1), "weight": "20%", "label": "Data Durability"},
            "failover_readiness": {"score": round(failover_score, 1), "weight": "15%", "label": "Failover Readiness"},
            "recovery_freshness": {"score": round(freshness_score, 1), "weight": "10%", "label": "Recovery Freshness"},
            "cross_region": {"score": round(cross_region_score, 1), "weight": "10%", "label": "Cross-Region Posture"},
        },
        "findings": all_findings,
        "spofs": spofs,
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
