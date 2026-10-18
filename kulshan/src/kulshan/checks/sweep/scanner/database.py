"""Scan for orphaned database resources: old snapshots, stopped RDS instances."""

from datetime import datetime, timezone
from typing import Dict, List, Tuple
from ..utils.aws import safe_api_call, paginate_all

from .evidence import qualify_findings


def scan_database(session, regions, progress=None, task_id=None) -> Tuple[List[Dict], List[str]]:
    """Find orphaned database resources across all regions."""
    orphans = []
    errors = []

    for region in regions:
        try:
            rds = session.client("rds", region_name=region)

            # --- Old Manual RDS Snapshots ---
            snaps, err = paginate_all(
                rds, "describe_db_snapshots", "DBSnapshots", SnapshotType="manual"
            )
            if err:
                errors.append(f"RDS Snapshots ({region}): {err}")
            else:
                for snap in snaps:
                    created = snap.get("SnapshotCreateTime", datetime.now(timezone.utc))
                    age_days = (datetime.now(timezone.utc) - created).days
                    if age_days < 90:
                        continue  # Only flag snapshots older than 90 days
                    size_gb = snap.get("AllocatedStorage", "unknown")

                    orphans.append(
                        {
                            "resource_id": snap["DBSnapshotIdentifier"],
                            "resource_type": "RDS Snapshot (manual)",
                            "category": "database",
                            "region": region,
                            "reason": f"Manual snapshot, {age_days} days old ({size_gb} GB, engine: {snap.get('Engine', '?')})",
                            "age_days": age_days,
                            "monthly_cost": None,
                            "created": created.isoformat(),
                            "tags": {},
                            "cleanup_action": f"aws rds delete-db-snapshot --db-snapshot-identifier {snap['DBSnapshotIdentifier']} --region {region}",
                            "confidence": "medium",
                        }
                    )

            # --- Stopped RDS Instances (still billed for storage) ---
            instances, err = paginate_all(rds, "describe_db_instances", "DBInstances")
            if err:
                errors.append(f"RDS Instances ({region}): {err}")
            else:
                for db in instances:
                    if db.get("DBInstanceStatus") == "stopped":
                        size_gb = db.get("AllocatedStorage", "unknown")
                        db_class = db.get("DBInstanceClass", "?")

                        orphans.append(
                            {
                                "resource_id": db["DBInstanceIdentifier"],
                                "resource_type": "RDS Instance (stopped)",
                                "category": "database",
                                "region": region,
                                "reason": f"Currently stopped, allocated storage {size_gb} GB ({db_class}, {db.get('Engine', '?')})",
                                "age_days": None,
                                "monthly_cost": None,
                                "created": None,
                                "tags": {},
                                "cleanup_action": f"# Review before deleting: aws rds delete-db-instance --db-instance-identifier {db['DBInstanceIdentifier']} --skip-final-snapshot --region {region}",
                                "confidence": "low",
                            }
                        )

        except Exception as exc:
            errors.append(f"database ({region}): incomplete check: {exc}")

        if progress and task_id:
            progress.advance(task_id)

    return qualify_findings(orphans), errors
