"""Scan resource freshness: Lambda runtimes, RDS engines, EC2 age, certs, EBS types."""

from datetime import datetime, timezone
from typing import Dict, List, Tuple
from ..utils.aws import safe_api_call, paginate_all
from .eol_db import LAMBDA_EOL, RDS_EOL, EKS_EOL, REDIS_EOL


def scan_freshness(session, regions, progress=None, task_id=None) -> Tuple[Dict, List[str]]:
    """Full freshness audit across all resource types."""
    findings = []
    errors = []
    aging = []  # All aging resources
    stats = {"lambda": 0, "rds": 0, "ec2": 0, "certs": 0, "ebs_gp2": 0, "eks": 0, "cache": 0}

    for region in regions:
        # --- Lambda Runtimes ---
        try:
            lam = session.client("lambda", region_name=region)
            fns, err = paginate_all(lam, "list_functions", "Functions")
            if err:
                errors.append(f"Lambda ({region}): {err}")
            else:
                for fn in fns:
                    runtime = fn.get("Runtime", "")
                    eol_info = LAMBDA_EOL.get(runtime)
                    if eol_info and eol_info["status"] != "current":
                        stats["lambda"] += 1
                        aging.append({
                            "resource_id": fn["FunctionName"],
                            "resource_type": "Lambda Function",
                            "category": "runtime",
                            "region": region,
                            "current": runtime,
                            "eol_date": eol_info.get("eol"),
                            "status": eol_info["status"],
                            "upgrade_to": eol_info.get("upgrade"),
                            "severity": "critical" if eol_info["status"] == "eol" else "warning",
                            "monthly_cost_impact": 0,
                        })
        except Exception as e:
            errors.append(f"Lambda ({region}): {e}")

        # --- RDS Engine Versions ---
        try:
            rds = session.client("rds", region_name=region)
            instances, err = paginate_all(rds, "describe_db_instances", "DBInstances")
            if err:
                errors.append(f"RDS ({region}): {err}")
            else:
                for db in instances:
                    engine = db.get("Engine", "")
                    version = db.get("EngineVersion", "")
                    major = version.split(".")[0] if "." in version else version
                    # For postgres, use major only; for mysql, use major.minor
                    engine_key = engine.replace("aurora-", "").replace("postgresql", "postgres")
                    if engine_key in RDS_EOL:
                        eol_info = RDS_EOL[engine_key].get(major) or RDS_EOL[engine_key].get(f"{major}.{version.split('.')[1]}" if "." in version else major)
                        if eol_info and eol_info["status"] != "current":
                            stats["rds"] += 1
                            monthly_surcharge = 0
                            if eol_info.get("surcharge"):
                                # Rough estimate: instance cost * 1.0 (the surcharge portion)
                                monthly_surcharge = _estimate_rds_surcharge(db)
                            aging.append({
                                "resource_id": db["DBInstanceIdentifier"],
                                "resource_type": f"RDS ({engine} {version})",
                                "category": "engine",
                                "region": region,
                                "current": f"{engine} {version}",
                                "eol_date": eol_info.get("eos"),
                                "status": eol_info["status"],
                                "upgrade_to": eol_info.get("upgrade"),
                                "severity": "critical" if eol_info["status"] == "extended_support" else "warning",
                                "monthly_cost_impact": monthly_surcharge,
                            })
        except Exception as e:
            errors.append(f"RDS ({region}): {e}")

        # --- EC2 Instance Age ---
        try:
            ec2 = session.client("ec2", region_name=region)
            resp, err = safe_api_call(ec2, "describe_instances",
                                       Filters=[{"Name": "instance-state-name", "Values": ["running"]}])
            if not err:
                for res in (resp or {}).get("Reservations", []):
                    for inst in res.get("Instances", []):
                        launch = inst.get("LaunchTime", datetime.now(timezone.utc))
                        age_days = (datetime.now(timezone.utc) - launch).days
                        if age_days >= 180:
                            stats["ec2"] += 1
                            sev = "critical" if age_days >= 365 else "warning"
                            aging.append({
                                "resource_id": inst["InstanceId"],
                                "resource_type": f"EC2 ({inst.get('InstanceType', '?')})",
                                "category": "instance_age",
                                "region": region,
                                "current": f"{age_days} days uptime",
                                "eol_date": None,
                                "status": "stale" if age_days >= 365 else "aging",
                                "upgrade_to": "Refresh AMI / relaunch",
                                "severity": sev,
                                "monthly_cost_impact": 0,
                            })
        except Exception as e:
            errors.append(f"EC2 age ({region}): {e}")

        # --- ACM Certificates ---
        try:
            acm = session.client("acm", region_name=region)
            certs, err = paginate_all(acm, "list_certificates", "CertificateSummaryList")
            if not err:
                for cert in certs:
                    cert_arn = cert.get("CertificateArn", "")
                    detail_resp, _ = safe_api_call(acm, "describe_certificate", CertificateArn=cert_arn)
                    if detail_resp:
                        cert_detail = detail_resp.get("Certificate", {})
                        not_after = cert_detail.get("NotAfter")
                        if not_after:
                            days_left = (not_after - datetime.now(timezone.utc)).days
                            renewal = cert_detail.get("RenewalSummary", {}).get("RenewalStatus", "")
                            if days_left <= 90:
                                stats["certs"] += 1
                                sev = "critical" if days_left <= 30 else "warning"
                                aging.append({
                                    "resource_id": cert_detail.get("DomainName", cert_arn[:40]),
                                    "resource_type": "ACM Certificate",
                                    "category": "certificate",
                                    "region": region,
                                    "current": f"Expires in {days_left} days" + (f" (renewal: {renewal})" if renewal else ""),
                                    "eol_date": not_after.isoformat(),
                                    "status": "expiring",
                                    "upgrade_to": "Renew or replace",
                                    "severity": sev,
                                    "monthly_cost_impact": 0,
                                })
        except Exception as e:
            errors.append(f"ACM ({region}): {e}")

        # --- EBS gp2 volumes ---
        try:
            resp, err = safe_api_call(ec2, "describe_volumes",
                                       Filters=[{"Name": "volume-type", "Values": ["gp2"]}])
            if not err:
                gp2_vols = (resp or {}).get("Volumes", [])
                for vol in gp2_vols:
                    stats["ebs_gp2"] += 1
                    size_gb = vol.get("Size", 0)
                    savings = size_gb * 0.02  # ~$0.02/GB savings gp2→gp3
                    aging.append({
                        "resource_id": vol["VolumeId"],
                        "resource_type": f"EBS Volume (gp2, {size_gb} GB)",
                        "category": "storage_modernization",
                        "region": region,
                        "current": "gp2",
                        "eol_date": None,
                        "status": "outdated",
                        "upgrade_to": "gp3 (20% cheaper, better performance)",
                        "severity": "modernize",
                        "monthly_cost_impact": -savings,
                    })
        except Exception as e:
            errors.append(f"EBS ({region}): {e}")

        # --- EKS Versions ---
        try:
            eks = session.client("eks", region_name=region)
            clusters, err = paginate_all(eks, "list_clusters", "clusters")
            if not err:
                for name in clusters:
                    desc, _ = safe_api_call(eks, "describe_cluster", name=name)
                    if desc:
                        ver = desc.get("cluster", {}).get("version", "")
                        eol_info = EKS_EOL.get(ver)
                        if eol_info and eol_info["status"] != "current":
                            stats["eks"] += 1
                            aging.append({
                                "resource_id": name,
                                "resource_type": f"EKS Cluster (k8s {ver})",
                                "category": "runtime",
                                "region": region,
                                "current": f"Kubernetes {ver}",
                                "eol_date": eol_info.get("eos"),
                                "status": eol_info["status"],
                                "upgrade_to": eol_info.get("upgrade"),
                                "severity": "critical" if eol_info["status"] == "eol" else "warning",
                                "monthly_cost_impact": 0,
                            })
        except Exception as e:
            errors.append(f"EKS ({region}): {e}")

        # --- ElastiCache Redis ---
        try:
            ec_client = session.client("elasticache", region_name=region)
            groups, err = paginate_all(ec_client, "describe_replication_groups", "ReplicationGroups")
            if not err:
                for g in groups:
                    # Get engine version from member clusters
                    members = g.get("MemberClusters", [])
                    if members:
                        cc_resp, _ = safe_api_call(ec_client, "describe_cache_clusters", CacheClusterId=members[0])
                        if cc_resp:
                            for cc in cc_resp.get("CacheClusters", []):
                                ver = cc.get("EngineVersion", "")
                                major = ver.split(".")[0]
                                redis_info = REDIS_EOL.get(major)
                                if redis_info and redis_info["status"] != "current":
                                    stats["cache"] += 1
                                    aging.append({
                                        "resource_id": g["ReplicationGroupId"],
                                        "resource_type": f"ElastiCache Redis {ver}",
                                        "category": "runtime",
                                        "region": region,
                                        "current": f"Redis {ver}",
                                        "eol_date": None,
                                        "status": redis_info["status"],
                                        "upgrade_to": f"Redis {redis_info['upgrade']}",
                                        "severity": "critical" if redis_info["status"] == "eol" else "warning",
                                        "monthly_cost_impact": 0,
                                    })
        except Exception as e:
            errors.append(f"ElastiCache ({region}): {e}")

        if progress and task_id:
            progress.advance(task_id)

    return {"aging": aging, "stats": stats, "findings": findings}, errors


def _estimate_rds_surcharge(db):
    """Rough estimate of RDS Extended Support monthly surcharge."""
    db_class = db.get("DBInstanceClass", "")
    multi_az = db.get("MultiAZ", False)
    # Very rough: small=50, medium=150, large=400, xlarge=800
    base = 50
    if "large" in db_class: base = 200
    if "xlarge" in db_class: base = 400
    if "2xlarge" in db_class: base = 600
    if "4xlarge" in db_class: base = 1000
    if multi_az: base *= 2
    return base
