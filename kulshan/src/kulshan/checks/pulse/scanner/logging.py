"""Scan logging coverage: CloudTrail, VPC Flow Logs, S3 access logs, RDS/ECS/EKS logging."""

from typing import Dict, List, Tuple
from ..utils.aws import safe_api_call, paginate_all


def scan_logging(session, regions, progress=None, task_id=None) -> Tuple[Dict, List[str]]:
    """Audit logging coverage across all regions."""
    findings = []
    errors = []
    stats = {
        "cloudtrail_enabled": False,
        "cloudtrail_multi_region": False,
        "cloudtrail_log_validation": False,
        "vpc_flow_logs": {"total_vpcs": 0, "with_flow_logs": 0},
        "s3_access_logging": {"total_buckets": 0, "with_logging": 0},
        "rds_logging": {"total": 0, "with_enhanced": 0},
        "log_groups_total": 0,
        "log_groups_with_retention": 0,
        "log_groups_no_retention": 0,
    }

    # --- CloudTrail (global check) ---
    ct = session.client("cloudtrail", region_name="us-east-1")
    trails_resp, err = safe_api_call(ct, "describe_trails")
    if err:
        errors.append(f"CloudTrail: {err}")
    else:
        trails = (trails_resp or {}).get("trailList", [])
        if trails:
            stats["cloudtrail_enabled"] = True
            for trail in trails:
                if trail.get("IsMultiRegionTrail"):
                    stats["cloudtrail_multi_region"] = True
                if trail.get("LogFileValidationEnabled"):
                    stats["cloudtrail_log_validation"] = True
        else:
            findings.append({
                "category": "logging",
                "severity": "critical",
                "title": "CloudTrail is NOT enabled",
                "detail": "No trails found. All API activity is unaudited.",
                "recommendation": "Enable CloudTrail with multi-region and log file validation.",
            })

    if stats["cloudtrail_enabled"] and not stats["cloudtrail_multi_region"]:
        findings.append({
            "category": "logging",
            "severity": "high",
            "title": "CloudTrail is not multi-region",
            "detail": "API activity in non-home regions is not being logged.",
            "recommendation": "Enable multi-region trail.",
        })

    # --- S3 Access Logging ---
    s3 = session.client("s3", region_name="us-east-1")
    buckets_resp, err = safe_api_call(s3, "list_buckets")
    if not err:
        buckets = (buckets_resp or {}).get("Buckets", [])
        stats["s3_access_logging"]["total_buckets"] = len(buckets)
        for bucket in buckets:
            log_resp, _ = safe_api_call(s3, "get_bucket_logging", Bucket=bucket["Name"])
            if log_resp and log_resp.get("LoggingEnabled"):
                stats["s3_access_logging"]["with_logging"] += 1

        no_log = stats["s3_access_logging"]["total_buckets"] - stats["s3_access_logging"]["with_logging"]
        if no_log > 0 and stats["s3_access_logging"]["total_buckets"] > 0:
            pct = no_log / stats["s3_access_logging"]["total_buckets"] * 100
            findings.append({
                "category": "logging",
                "severity": "medium" if pct < 50 else "high",
                "title": f"{no_log}/{stats['s3_access_logging']['total_buckets']} S3 buckets have no access logging ({pct:.0f}%)",
                "detail": "Access patterns and unauthorized access attempts are invisible.",
                "recommendation": "Enable server access logging for buckets with sensitive data.",
            })

    for region in regions:
        ec2 = session.client("ec2", region_name=region)

        # --- VPC Flow Logs ---
        vpcs_resp, err = safe_api_call(ec2, "describe_vpcs")
        if not err:
            vpcs = (vpcs_resp or {}).get("Vpcs", [])
            stats["vpc_flow_logs"]["total_vpcs"] += len(vpcs)

            flow_resp, _ = safe_api_call(ec2, "describe_flow_logs")
            flow_vpc_ids = set()
            for fl in (flow_resp or {}).get("FlowLogs", []):
                rid = fl.get("ResourceId", "")
                if rid.startswith("vpc-"):
                    flow_vpc_ids.add(rid)

            for vpc in vpcs:
                if vpc["VpcId"] in flow_vpc_ids:
                    stats["vpc_flow_logs"]["with_flow_logs"] += 1

        # --- CloudWatch Log Groups retention ---
        logs = session.client("logs", region_name=region)
        groups, err = paginate_all(logs, "describe_log_groups", "logGroups")
        if not err:
            stats["log_groups_total"] += len(groups)
            for lg in groups:
                if lg.get("retentionInDays"):
                    stats["log_groups_with_retention"] += 1
                else:
                    stats["log_groups_no_retention"] += 1

        # --- RDS Enhanced Monitoring ---
        rds = session.client("rds", region_name=region)
        instances, err = paginate_all(rds, "describe_db_instances", "DBInstances")
        if not err:
            for db in instances:
                stats["rds_logging"]["total"] += 1
                if db.get("MonitoringInterval", 0) > 0:
                    stats["rds_logging"]["with_enhanced"] += 1

        if progress and task_id:
            progress.advance(task_id)

    # VPC flow log findings
    no_flow = stats["vpc_flow_logs"]["total_vpcs"] - stats["vpc_flow_logs"]["with_flow_logs"]
    if no_flow > 0:
        findings.append({
            "category": "logging",
            "severity": "high",
            "title": f"{no_flow}/{stats['vpc_flow_logs']['total_vpcs']} VPCs have no flow logs",
            "detail": "Network traffic is invisible. Cannot detect lateral movement or data exfiltration.",
            "recommendation": "Enable VPC Flow Logs for all production VPCs.",
        })

    # Log retention findings
    if stats["log_groups_no_retention"] > 0:
        findings.append({
            "category": "logging",
            "severity": "medium",
            "title": f"{stats['log_groups_no_retention']} log groups have no retention policy (never expire)",
            "detail": "Logs accumulate indefinitely, increasing storage costs.",
            "recommendation": "Set retention policies on all log groups (e.g., 90 or 365 days).",
        })

    return {"stats": stats, "findings": findings}, errors
