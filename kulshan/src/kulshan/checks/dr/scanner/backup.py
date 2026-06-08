"""Scan AWS Backup coverage: plans, vaults, recovery points, protected resources."""

from datetime import datetime, timezone
from typing import Dict, List, Tuple
from ..utils.aws import safe_api_call, paginate_all


def scan_backup(session, regions, progress=None, task_id=None) -> Tuple[Dict, List[str]]:
    """Audit AWS Backup coverage across all regions."""
    findings = []
    errors = []
    stats = {
        "backup_plans": 0,
        "backup_vaults": 0,
        "recovery_points": 0,
        "protected_resources": 0,
        "unprotected_critical": [],
        "stale_recovery_points": [],
        "freshest_by_resource": {},
    }

    for region in regions:
        backup = session.client("backup", region_name=region)

        # --- Backup Plans ---
        plans, err = paginate_all(backup, "list_backup_plans", "BackupPlansList")
        if err:
            errors.append(f"Backup Plans ({region}): {err}")
        else:
            stats["backup_plans"] += len(plans)

        # --- Backup Vaults ---
        vaults, err = paginate_all(backup, "list_backup_vaults", "BackupVaultList")
        if err:
            errors.append(f"Backup Vaults ({region}): {err}")
        else:
            stats["backup_vaults"] += len(vaults)

            # Recovery points per vault
            for vault in vaults:
                vault_name = vault["BackupVaultName"]
                rps, rp_err = paginate_all(backup, "list_recovery_points_by_backup_vault",
                                           "RecoveryPoints", BackupVaultName=vault_name)
                if rp_err:
                    errors.append(f"Recovery Points ({region}/{vault_name}): {rp_err}")
                    continue

                stats["recovery_points"] += len(rps)

                for rp in rps:
                    resource_arn = rp.get("ResourceArn", "")
                    created = rp.get("CreationDate", datetime.now(timezone.utc))
                    age_hours = (datetime.now(timezone.utc) - created).total_seconds() / 3600

                    # Track freshest recovery point per resource
                    if resource_arn not in stats["freshest_by_resource"] or \
                       age_hours < stats["freshest_by_resource"][resource_arn]["age_hours"]:
                        stats["freshest_by_resource"][resource_arn] = {
                            "age_hours": round(age_hours, 1),
                            "created": created.isoformat(),
                            "vault": vault_name,
                            "region": region,
                        }

                    # Flag stale recovery points (older than 7 days)
                    if age_hours > 168:
                        stats["stale_recovery_points"].append({
                            "resource_arn": resource_arn,
                            "age_hours": round(age_hours, 1),
                            "vault": vault_name,
                            "region": region,
                        })

        # --- Protected Resources ---
        protected, err = paginate_all(backup, "list_protected_resources", "Results")
        if err:
            errors.append(f"Protected Resources ({region}): {err}")
        else:
            stats["protected_resources"] += len(protected)

        if progress and task_id:
            progress.advance(task_id)

    # Generate findings
    if stats["backup_plans"] == 0:
        findings.append({
            "category": "backup",
            "severity": "critical",
            "title": "No AWS Backup plans configured",
            "detail": "No backup plans found in any region. Critical data is unprotected.",
            "recommendation": "Create AWS Backup plans for RDS, EBS, DynamoDB, and EFS resources.",
        })

    if stats["protected_resources"] == 0 and stats["backup_plans"] > 0:
        findings.append({
            "category": "backup",
            "severity": "high",
            "title": "Backup plans exist but no resources are protected",
            "detail": f"{stats['backup_plans']} backup plan(s) found but 0 resources assigned.",
            "recommendation": "Assign critical resources to backup plans.",
        })

    stale_count = len(stats["stale_recovery_points"])
    if stale_count > 0:
        findings.append({
            "category": "backup",
            "severity": "high",
            "title": f"{stale_count} resources have stale recovery points (>7 days old)",
            "detail": "Recovery points older than 7 days may not meet RPO requirements.",
            "recommendation": "Review backup frequency and ensure schedules are running.",
        })

    return {"stats": stats, "findings": findings}, errors
