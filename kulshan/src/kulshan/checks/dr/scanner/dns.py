"""Scan DNS & routing resilience: Route 53 health checks, failover routing."""

from typing import Dict, List, Tuple
from ..utils.aws import safe_api_call, paginate_all


def scan_dns(session, regions, progress=None, task_id=None) -> Tuple[Dict, List[str]]:
    """Audit Route 53 DNS resilience."""
    findings = []
    errors = []
    stats = {
        "hosted_zones": 0,
        "health_checks": 0,
        "failover_records": 0,
        "weighted_records": 0,
        "zones_without_health_checks": [],
        "record_sets_total": 0,
    }

    r53 = session.client("route53", region_name="us-east-1")

    # --- Health Checks ---
    hc_resp, err = safe_api_call(r53, "list_health_checks")
    if err:
        errors.append(f"Route53 Health Checks: {err}")
    else:
        checks = (hc_resp or {}).get("HealthChecks", [])
        stats["health_checks"] = len(checks)

    # --- Hosted Zones ---
    zones_resp, err = safe_api_call(r53, "list_hosted_zones")
    if err:
        errors.append(f"Route53 Zones: {err}")
    else:
        zones = (zones_resp or {}).get("HostedZones", [])
        stats["hosted_zones"] = len(zones)

        for zone in zones:
            zone_id = zone["Id"].split("/")[-1]
            zone_name = zone.get("Name", "?")

            # Get record sets
            records_resp, rec_err = safe_api_call(r53, "list_resource_record_sets",
                                                   HostedZoneId=zone_id)
            if rec_err:
                errors.append(f"Route53 Records ({zone_name}): {rec_err}")
                continue

            records = (records_resp or {}).get("ResourceRecordSets", [])
            stats["record_sets_total"] += len(records)

            has_health_check = False
            for record in records:
                if record.get("HealthCheckId"):
                    has_health_check = True
                failover = record.get("Failover")
                if failover:
                    stats["failover_records"] += 1
                weight = record.get("Weight")
                if weight is not None:
                    stats["weighted_records"] += 1

            if not has_health_check and not zone.get("Config", {}).get("PrivateZone", False):
                stats["zones_without_health_checks"].append(zone_name)

    # Generate findings
    if stats["health_checks"] == 0 and stats["hosted_zones"] > 0:
        findings.append({
            "category": "dns",
            "severity": "high",
            "title": "No Route 53 health checks configured",
            "detail": f"{stats['hosted_zones']} hosted zone(s) but zero health checks. DNS failover is impossible.",
            "recommendation": "Create health checks for primary endpoints to enable automatic DNS failover.",
        })

    if stats["failover_records"] == 0 and stats["hosted_zones"] > 0:
        findings.append({
            "category": "dns",
            "severity": "medium",
            "title": "No failover routing policies configured",
            "detail": "No DNS records use failover routing. Traffic cannot automatically redirect during outages.",
            "recommendation": "Configure failover routing for critical endpoints.",
        })

    no_hc_count = len(stats["zones_without_health_checks"])
    if no_hc_count > 0:
        findings.append({
            "category": "dns",
            "severity": "medium",
            "title": f"{no_hc_count} public hosted zone(s) have no health-checked records",
            "detail": "These zones cannot perform automatic failover.",
            "recommendation": "Add health checks to A/AAAA/CNAME records for critical services.",
        })

    if progress and task_id:
        progress.advance(task_id)

    return {"stats": stats, "findings": findings}, errors
