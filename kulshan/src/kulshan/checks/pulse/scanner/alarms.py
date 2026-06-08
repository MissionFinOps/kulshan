"""Scan alarm coverage: CloudWatch alarms vs critical resources."""

from typing import Dict, List, Tuple
from collections import defaultdict
from ..utils.aws import safe_api_call, paginate_all


def scan_alarms(session, regions, progress=None, task_id=None) -> Tuple[Dict, List[str]]:
    """Audit CloudWatch alarm coverage across all regions."""
    findings = []
    errors = []
    stats = {
        "total_alarms": 0,
        "alarms_ok": 0,
        "alarms_alarm": 0,
        "alarms_insufficient": 0,
        "alarms_by_namespace": {},
        "resources_without_alarms": [],
        "sns_topics": 0,
        "alarms_without_actions": 0,
    }

    # Blind spot matrix: resource type -> {total, monitored}
    blind_spots = {
        "EC2 Instances": {"total": 0, "monitored": set(), "namespace": "AWS/EC2", "dim": "InstanceId"},
        "RDS Instances": {"total": 0, "monitored": set(), "namespace": "AWS/RDS", "dim": "DBInstanceIdentifier"},
        "ALB": {"total": 0, "monitored": set(), "namespace": "AWS/ApplicationELB", "dim": "LoadBalancer"},
        "Lambda Functions": {"total": 0, "monitored": set(), "namespace": "AWS/Lambda", "dim": "FunctionName"},
        "NAT Gateways": {"total": 0, "monitored": set(), "namespace": "AWS/NATGateway", "dim": "NatGatewayId"},
    }

    for region in regions:
        cw = session.client("cloudwatch", region_name=region)

        # --- All alarms ---
        alarms, err = paginate_all(cw, "describe_alarms", "MetricAlarms")
        if err:
            errors.append(f"Alarms ({region}): {err}")
        else:
            stats["total_alarms"] += len(alarms)
            for alarm in alarms:
                state = alarm.get("StateValue", "")
                if state == "OK":
                    stats["alarms_ok"] += 1
                elif state == "ALARM":
                    stats["alarms_alarm"] += 1
                elif state == "INSUFFICIENT_DATA":
                    stats["alarms_insufficient"] += 1

                ns = alarm.get("Namespace", "Other")
                stats["alarms_by_namespace"][ns] = stats["alarms_by_namespace"].get(ns, 0) + 1

                # Check if alarm has actions
                actions = (alarm.get("AlarmActions", []) +
                          alarm.get("OKActions", []) +
                          alarm.get("InsufficientDataActions", []))
                if not actions:
                    stats["alarms_without_actions"] += 1

                # Track which resources have alarms (for blind spot detection)
                dims = {d["Name"]: d["Value"] for d in alarm.get("Dimensions", [])}
                for rtype, info in blind_spots.items():
                    if alarm.get("Namespace") == info["namespace"] and info["dim"] in dims:
                        info["monitored"].add(dims[info["dim"]])

        # --- Count resources for blind spot matrix ---
        ec2 = session.client("ec2", region_name=region)

        # EC2
        inst_resp, _ = safe_api_call(ec2, "describe_instances",
                                      Filters=[{"Name": "instance-state-name", "Values": ["running"]}])
        for res in (inst_resp or {}).get("Reservations", []):
            blind_spots["EC2 Instances"]["total"] += len(res.get("Instances", []))

        # RDS
        rds = session.client("rds", region_name=region)
        rds_instances, _ = paginate_all(rds, "describe_db_instances", "DBInstances")
        blind_spots["RDS Instances"]["total"] += len(rds_instances)

        # ALB
        try:
            elbv2 = session.client("elbv2", region_name=region)
            lbs, _ = paginate_all(elbv2, "describe_load_balancers", "LoadBalancers")
            blind_spots["ALB"]["total"] += len([lb for lb in lbs if lb.get("Type") == "application"])
        except Exception:
            pass

        # Lambda
        try:
            lam = session.client("lambda", region_name=region)
            fns, _ = paginate_all(lam, "list_functions", "Functions")
            blind_spots["Lambda Functions"]["total"] += len(fns)
        except Exception:
            pass

        # NAT GW
        nat_resp, _ = safe_api_call(ec2, "describe_nat_gateways",
                                     Filters=[{"Name": "state", "Values": ["available"]}])
        blind_spots["NAT Gateways"]["total"] += len((nat_resp or {}).get("NatGateways", []))

        # SNS topics
        try:
            sns = session.client("sns", region_name=region)
            topics, _ = paginate_all(sns, "list_topics", "Topics")
            stats["sns_topics"] += len(topics)
        except Exception:
            pass

        if progress and task_id:
            progress.advance(task_id)

    # Generate blind spot findings
    for rtype, info in blind_spots.items():
        total = info["total"]
        monitored = len(info["monitored"])
        if total > 0:
            unmonitored = total - monitored
            pct_monitored = monitored / total * 100
            if unmonitored > 0:
                findings.append({
                    "category": "alarms",
                    "severity": "high" if pct_monitored < 50 else "medium",
                    "title": f"{unmonitored}/{total} {rtype} have no CloudWatch alarms ({pct_monitored:.0f}% covered)",
                    "detail": f"These resources can fail silently without triggering any notification.",
                    "recommendation": f"Create alarms for critical metrics on all {rtype}.",
                })

    if stats["total_alarms"] == 0:
        findings.append({
            "category": "alarms",
            "severity": "critical",
            "title": "No CloudWatch alarms configured",
            "detail": "Zero alarms across all regions. All failures are silent.",
            "recommendation": "Create alarms for CPU, memory, disk, error rates on critical resources.",
        })

    if stats["alarms_without_actions"] > 0:
        findings.append({
            "category": "alarms",
            "severity": "high",
            "title": f"{stats['alarms_without_actions']} alarms have no notification actions",
            "detail": "These alarms trigger but nobody gets notified.",
            "recommendation": "Add SNS actions to all alarms.",
        })

    insufficient = stats["alarms_insufficient"]
    if insufficient > 5:
        findings.append({
            "category": "alarms",
            "severity": "medium",
            "title": f"{insufficient} alarms in INSUFFICIENT_DATA state",
            "detail": "These alarms are not receiving metrics. They may be misconfigured or the resource was deleted.",
            "recommendation": "Review and clean up stale alarms.",
        })

    # Convert sets to counts for serialization
    blind_spot_summary = {}
    for rtype, info in blind_spots.items():
        blind_spot_summary[rtype] = {
            "total": info["total"],
            "monitored": len(info["monitored"]),
            "unmonitored": info["total"] - len(info["monitored"]),
            "coverage_pct": round(len(info["monitored"]) / info["total"] * 100, 1) if info["total"] > 0 else 0,
        }

    stats["blind_spots"] = blind_spot_summary
    return {"stats": stats, "findings": findings}, errors
