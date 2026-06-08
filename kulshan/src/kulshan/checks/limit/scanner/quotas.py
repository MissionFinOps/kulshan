"""Scan service quotas and current usage across key AWS services."""

from typing import Dict, List, Tuple
from ..utils.aws import safe_api_call, paginate_all

# High-value quotas to always check with direct resource counting
CRITICAL_QUOTAS = [
    {"service": "ec2", "name": "Running On-Demand Standard instances", "counter": "_count_ec2_instances"},
    {"service": "vpc", "name": "VPCs per Region", "counter": "_count_vpcs"},
    {"service": "vpc", "name": "Security groups per Region", "counter": "_count_security_groups"},
    {"service": "elasticloadbalancing", "name": "Application Load Balancers per Region", "counter": "_count_albs"},
    {"service": "iam", "name": "IAM Roles", "counter": "_count_iam_roles"},
    {"service": "iam", "name": "IAM Users", "counter": "_count_iam_users"},
    {"service": "iam", "name": "Customer managed policies", "counter": "_count_iam_policies"},
    {"service": "lambda", "name": "Lambda concurrent executions", "counter": None},
    {"service": "rds", "name": "DB instances", "counter": "_count_rds_instances"},
    {"service": "cloudformation", "name": "Stack count", "counter": "_count_cfn_stacks"},
    {"service": "ebs", "name": "Snapshots per Region", "counter": "_count_ebs_snapshots"},
    {"service": "s3", "name": "Buckets", "counter": "_count_s3_buckets"},
]


def scan_quotas(session, regions, quick=False, progress=None, task_id=None) -> Tuple[List[Dict], List[str]]:
    """Scan service quotas and compute utilization percentages."""
    quotas = []
    errors = []

    # Phase 1: Service Quotas API (region-scoped services)
    for region in regions:
        sq = session.client("service-quotas", region_name=region)

        # Get all services
        services, err = paginate_all(sq, "list_services", "Services")
        if err:
            errors.append(f"Service Quotas ({region}): {err}")
            if progress and task_id:
                progress.advance(task_id)
            continue

        # For quick mode, only check top services
        if quick:
            top_codes = {"ec2", "vpc", "elasticloadbalancing", "lambda", "rds",
                         "cloudformation", "ebs", "s3", "iam", "dynamodb",
                         "elasticache", "ecs", "eks", "sns", "sqs"}
            services = [s for s in services if s.get("ServiceCode", "") in top_codes]

        for svc in services:
            svc_code = svc.get("ServiceCode", "")
            svc_name = svc.get("ServiceName", svc_code)

            svc_quotas, q_err = paginate_all(sq, "list_service_quotas", "Quotas",
                                              ServiceCode=svc_code)
            if q_err:
                continue

            for q in svc_quotas:
                quota_value = q.get("Value")
                if quota_value is None or quota_value == 0:
                    continue

                usage_metric = q.get("UsageMetric")
                current_usage = None

                # Try to get usage from CloudWatch if metric exists
                if usage_metric:
                    current_usage = _get_usage_from_metric(session, region, usage_metric)

                utilization_pct = None
                if current_usage is not None and quota_value > 0:
                    utilization_pct = (current_usage / quota_value) * 100

                quotas.append({
                    "service_code": svc_code,
                    "service_name": svc_name,
                    "quota_name": q.get("QuotaName", "?"),
                    "quota_code": q.get("QuotaCode", "?"),
                    "quota_value": quota_value,
                    "current_usage": current_usage,
                    "utilization_pct": round(utilization_pct, 1) if utilization_pct is not None else None,
                    "region": region,
                    "adjustable": q.get("Adjustable", False),
                    "global_quota": q.get("GlobalQuota", False),
                })

        if progress and task_id:
            progress.advance(task_id)

    # Phase 2: Direct resource counting for critical quotas (fills gaps)
    _enrich_with_direct_counts(session, regions, quotas, errors)

    return quotas, errors


def _get_usage_from_metric(session, region, usage_metric):
    """Get current usage from CloudWatch metric."""
    try:
        namespace = usage_metric.get("MetricNamespace", "")
        metric_name = usage_metric.get("MetricName", "")
        dimensions = usage_metric.get("MetricDimensions", {})

        if not namespace or not metric_name:
            return None

        cw = session.client("cloudwatch", region_name=region)
        from datetime import datetime, timezone, timedelta
        end = datetime.now(timezone.utc)
        start = end - timedelta(hours=1)

        cw_dims = [{"Name": k, "Value": v} for k, v in dimensions.items()]

        resp = cw.get_metric_statistics(
            Namespace=namespace,
            MetricName=metric_name,
            Dimensions=cw_dims,
            StartTime=start, EndTime=end,
            Period=3600, Statistics=["Maximum"],
        )
        datapoints = resp.get("Datapoints", [])
        if datapoints:
            return max(dp.get("Maximum", 0) for dp in datapoints)
    except Exception:
        pass
    return None


def _enrich_with_direct_counts(session, regions, quotas, errors):
    """Fill in usage for critical quotas via direct API calls."""
    for region in regions:
        # EC2 instances
        _try_direct_count(session, region, quotas,
                          "ec2", "Running On-Demand Standard",
                          _count_ec2_instances, errors)
        # VPCs
        _try_direct_count(session, region, quotas,
                          "vpc", "VPCs per Region",
                          _count_vpcs, errors)
        # IAM (global, only run once)
        if region == regions[0]:
            _try_direct_count(session, region, quotas,
                              "iam", "Roles",
                              _count_iam_roles, errors)
            _try_direct_count(session, region, quotas,
                              "s3", "Buckets",
                              _count_s3_buckets, errors)


def _try_direct_count(session, region, quotas, svc_code, quota_name, counter_fn, errors):
    """Try to fill in a direct count for a quota that's missing usage data."""
    if counter_fn is None:
        return
    for q in quotas:
        if q["service_code"] == svc_code and q["region"] == region and quota_name.lower() in q["quota_name"].lower():
            if q["current_usage"] is None:
                try:
                    count = counter_fn(session, q["region"])
                    if count is not None:
                        q["current_usage"] = count
                        if q["quota_value"] > 0:
                            q["utilization_pct"] = round((count / q["quota_value"]) * 100, 1)
                except Exception as e:
                    errors.append(f"Direct count {svc_code}/{quota_name} ({region}): {e}")


def _count_ec2_instances(session, region):
    ec2 = session.client("ec2", region_name=region)
    resp, _ = safe_api_call(ec2, "describe_instances",
                            Filters=[{"Name": "instance-state-name", "Values": ["running"]}])
    return sum(len(r.get("Instances", [])) for r in (resp or {}).get("Reservations", []))


def _count_vpcs(session, region):
    ec2 = session.client("ec2", region_name=region)
    resp, _ = safe_api_call(ec2, "describe_vpcs")
    return len((resp or {}).get("Vpcs", []))


def _count_security_groups(session, region):
    ec2 = session.client("ec2", region_name=region)
    resp, _ = safe_api_call(ec2, "describe_security_groups")
    return len((resp or {}).get("SecurityGroups", []))


def _count_albs(session, region):
    elbv2 = session.client("elbv2", region_name=region)
    lbs, _ = paginate_all(elbv2, "describe_load_balancers", "LoadBalancers")
    return len([lb for lb in lbs if lb.get("Type") == "application"])


def _count_iam_roles(session, region):
    iam = session.client("iam")
    roles, _ = paginate_all(iam, "list_roles", "Roles")
    return len(roles)


def _count_iam_users(session, region):
    iam = session.client("iam")
    users, _ = paginate_all(iam, "list_users", "Users")
    return len(users)


def _count_iam_policies(session, region):
    iam = session.client("iam")
    policies, _ = paginate_all(iam, "list_policies", "Policies", Scope="Local")
    return len(policies)


def _count_rds_instances(session, region):
    rds = session.client("rds", region_name=region)
    instances, _ = paginate_all(rds, "describe_db_instances", "DBInstances")
    return len(instances)


def _count_cfn_stacks(session, region):
    cfn = session.client("cloudformation", region_name=region)
    stacks, _ = paginate_all(cfn, "list_stacks", "StackSummaries")
    return len([s for s in stacks if s.get("StackStatus") != "DELETE_COMPLETE"])


def _count_ebs_snapshots(session, region):
    ec2 = session.client("ec2", region_name=region)
    snaps, _ = paginate_all(ec2, "describe_snapshots", "Snapshots", OwnerIds=["self"])
    return len(snaps)


def _count_s3_buckets(session, region):
    s3 = session.client("s3", region_name="us-east-1")
    resp, _ = safe_api_call(s3, "list_buckets")
    return len((resp or {}).get("Buckets", []))
