"""Scan database resilience: RDS Multi-AZ, backups, DynamoDB PITR, ElastiCache."""

from datetime import datetime, timezone
from typing import Dict, List, Tuple
from ..utils.aws import safe_api_call, paginate_all


def scan_database(session, regions, progress=None, task_id=None) -> Tuple[Dict, List[str]]:
    """Audit database resilience across all regions."""
    findings = []
    errors = []
    stats = {
        "rds_instances": [],
        "rds_no_multi_az": [],
        "rds_no_backup": [],
        "rds_short_retention": [],
        "aurora_clusters": [],
        "dynamodb_tables": [],
        "dynamodb_no_pitr": [],
        "elasticache_groups": [],
        "elasticache_no_failover": [],
    }

    for region in regions:
        rds = session.client("rds", region_name=region)

        # --- RDS Instances ---
        instances, err = paginate_all(rds, "describe_db_instances", "DBInstances")
        if err:
            errors.append(f"RDS ({region}): {err}")
        else:
            for db in instances:
                db_id = db["DBInstanceIdentifier"]
                multi_az = db.get("MultiAZ", False)
                backup_retention = db.get("BackupRetentionPeriod", 0)
                engine = db.get("Engine", "?")
                db_class = db.get("DBInstanceClass", "?")
                storage_gb = db.get("AllocatedStorage", 0)

                info = {
                    "id": db_id, "region": region, "engine": engine,
                    "class": db_class, "storage_gb": storage_gb,
                    "multi_az": multi_az, "backup_retention": backup_retention,
                    "read_replicas": len(db.get("ReadReplicaDBInstanceIdentifiers", [])),
                }
                stats["rds_instances"].append(info)

                if not multi_az:
                    stats["rds_no_multi_az"].append(info)
                    findings.append({
                        "category": "database",
                        "severity": "critical" if storage_gb > 100 else "high",
                        "title": f"RDS '{db_id}' is NOT Multi-AZ",
                        "detail": f"{engine} {db_class}, {storage_gb} GB. Single AZ = single point of failure.",
                        "recommendation": "Enable Multi-AZ for automatic failover.",
                    })

                if backup_retention == 0:
                    stats["rds_no_backup"].append(info)
                    findings.append({
                        "category": "database",
                        "severity": "critical",
                        "title": f"RDS '{db_id}' has NO automated backups",
                        "detail": f"{engine} {db_class}, {storage_gb} GB. Data loss is permanent if instance fails.",
                        "recommendation": "Enable automated backups with retention >= 7 days.",
                    })
                elif backup_retention < 7:
                    stats["rds_short_retention"].append(info)
                    findings.append({
                        "category": "database",
                        "severity": "medium",
                        "title": f"RDS '{db_id}' has short backup retention ({backup_retention} days)",
                        "detail": "Less than 7 days of backup retention limits recovery options.",
                        "recommendation": "Increase backup retention to at least 7 days.",
                    })

        # --- Aurora Clusters ---
        clusters, err = paginate_all(rds, "describe_db_clusters", "DBClusters")
        if err:
            if "AccessDenied" not in str(err):
                errors.append(f"Aurora ({region}): {err}")
        else:
            for cluster in clusters:
                cluster_id = cluster["DBClusterIdentifier"]
                members = cluster.get("DBClusterMembers", [])
                multi_az = len(set(m.get("DBInstanceIdentifier", "") for m in members)) > 1
                info = {
                    "id": cluster_id, "region": region,
                    "engine": cluster.get("Engine", "?"),
                    "members": len(members), "multi_az": multi_az,
                }
                stats["aurora_clusters"].append(info)

                if len(members) == 1:
                    findings.append({
                        "category": "database",
                        "severity": "high",
                        "title": f"Aurora cluster '{cluster_id}' has only 1 instance",
                        "detail": "No read replica for failover. Recovery requires creating a new instance.",
                        "recommendation": "Add at least one Aurora replica in a different AZ.",
                    })

        # --- DynamoDB Tables ---
        try:
            ddb = session.client("dynamodb", region_name=region)
            tables, err = paginate_all(ddb, "list_tables", "TableNames")
            if err:
                errors.append(f"DynamoDB ({region}): {err}")
            else:
                for table_name in tables:
                    # Check PITR
                    pitr_resp, pitr_err = safe_api_call(ddb, "describe_continuous_backups",
                                                         TableName=table_name)
                    pitr_enabled = False
                    if not pitr_err and pitr_resp:
                        pitr_desc = pitr_resp.get("ContinuousBackupsDescription", {})
                        pitr_status = pitr_desc.get("PointInTimeRecoveryDescription", {}).get(
                            "PointInTimeRecoveryStatus", "DISABLED")
                        pitr_enabled = pitr_status == "ENABLED"

                    info = {"name": table_name, "region": region, "pitr": pitr_enabled}
                    stats["dynamodb_tables"].append(info)

                    if not pitr_enabled:
                        stats["dynamodb_no_pitr"].append(info)
                        findings.append({
                            "category": "database",
                            "severity": "high",
                            "title": f"DynamoDB table '{table_name}' has no Point-in-Time Recovery",
                            "detail": "Without PITR, accidental deletes or corruption cannot be recovered.",
                            "recommendation": "Enable PITR for all production DynamoDB tables.",
                        })
        except Exception as e:
            errors.append(f"DynamoDB ({region}): {e}")

        # --- ElastiCache Replication Groups ---
        try:
            ec = session.client("elasticache", region_name=region)
            groups, err = paginate_all(ec, "describe_replication_groups", "ReplicationGroups")
            if err:
                errors.append(f"ElastiCache ({region}): {err}")
            else:
                for group in groups:
                    group_id = group["ReplicationGroupId"]
                    auto_failover = group.get("AutomaticFailover", "disabled")
                    multi_az = group.get("MultiAZ", "disabled")
                    members = group.get("MemberClusters", [])

                    info = {
                        "id": group_id, "region": region,
                        "auto_failover": auto_failover, "multi_az": multi_az,
                        "members": len(members),
                    }
                    stats["elasticache_groups"].append(info)

                    if auto_failover == "disabled":
                        stats["elasticache_no_failover"].append(info)
                        findings.append({
                            "category": "database",
                            "severity": "high",
                            "title": f"ElastiCache '{group_id}' has no automatic failover",
                            "detail": f"{len(members)} node(s), failover={auto_failover}, multi-az={multi_az}.",
                            "recommendation": "Enable automatic failover and Multi-AZ.",
                        })
        except Exception as e:
            errors.append(f"ElastiCache ({region}): {e}")

        if progress and task_id:
            progress.advance(task_id)

    return {"stats": stats, "findings": findings}, errors
