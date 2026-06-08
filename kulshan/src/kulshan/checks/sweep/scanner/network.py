"""Scan for orphaned network resources: unused SGs, idle NAT GWs, idle LBs."""

from datetime import datetime, timezone
from typing import Dict, List, Tuple
from ..utils.aws import safe_api_call, paginate_all


def scan_network(session, regions, progress=None, task_id=None) -> Tuple[List[Dict], List[str]]:
    """Find orphaned network resources across all regions."""
    orphans = []
    errors = []

    for region in regions:
        ec2 = session.client("ec2", region_name=region)

        # --- Unused Security Groups ---
        resp, err = safe_api_call(ec2, "describe_security_groups")
        if err:
            errors.append(f"SG ({region}): {err}")
        else:
            # Find all SGs referenced by ENIs
            eni_resp, _ = safe_api_call(ec2, "describe_network_interfaces")
            used_sgs = set()
            for eni in (eni_resp or {}).get("NetworkInterfaces", []):
                for g in eni.get("Groups", []):
                    used_sgs.add(g["GroupId"])

            for sg in resp.get("SecurityGroups", []):
                if sg["GroupName"] == "default":
                    continue
                if sg["GroupId"] not in used_sgs:
                    orphans.append({
                        "resource_id": sg["GroupId"],
                        "resource_type": "Security Group",
                        "category": "network",
                        "region": region,
                        "reason": f"Not attached to any resource ({sg['GroupName']})",
                        "age_days": None,
                        "monthly_cost": 0,
                        "created": None,
                        "tags": {t["Key"]: t["Value"] for t in sg.get("Tags", [])},
                        "cleanup_action": f"aws ec2 delete-security-group --group-id {sg['GroupId']} --region {region}",
                        "confidence": "medium",
                    })

        # --- Idle NAT Gateways ---
        resp, err = safe_api_call(ec2, "describe_nat_gateways",
                                  Filters=[{"Name": "state", "Values": ["available"]}])
        if err:
            errors.append(f"NAT GW ({region}): {err}")
        else:
            cw = session.client("cloudwatch", region_name=region)
            for nat in resp.get("NatGateways", []):
                nat_id = nat["NatGatewayId"]
                created = nat.get("CreateTime", datetime.now(timezone.utc))
                age_days = (datetime.now(timezone.utc) - created).days

                # Check if NAT GW has had traffic in last 14 days
                idle = _check_nat_idle(cw, nat_id)
                if idle:
                    orphans.append({
                        "resource_id": nat_id,
                        "resource_type": "NAT Gateway",
                        "category": "network",
                        "region": region,
                        "reason": "Zero traffic in last 14 days",
                        "age_days": age_days,
                        "monthly_cost": 32.40 + 0,  # $0.045/hr base
                        "created": created.isoformat(),
                        "tags": {t["Key"]: t["Value"] for t in nat.get("Tags", [])},
                        "cleanup_action": f"aws ec2 delete-nat-gateway --nat-gateway-id {nat_id} --region {region}",
                        "confidence": "high",
                    })

        # --- Idle Load Balancers (ALB/NLB with zero healthy targets) ---
        try:
            elbv2 = session.client("elbv2", region_name=region)
            lbs, err = paginate_all(elbv2, "describe_load_balancers", "LoadBalancers")
            if err:
                errors.append(f"ELB ({region}): {err}")
            else:
                for lb in lbs:
                    lb_arn = lb["LoadBalancerArn"]
                    lb_name = lb.get("LoadBalancerName", "?")
                    lb_type = lb.get("Type", "application")
                    created = lb.get("CreatedTime", datetime.now(timezone.utc))
                    age_days = (datetime.now(timezone.utc) - created).days

                    # Check target groups
                    tg_resp, _ = safe_api_call(elbv2, "describe_target_groups",
                                               LoadBalancerArn=lb_arn)
                    tgs = (tg_resp or {}).get("TargetGroups", [])

                    if not tgs:
                        # LB with no target groups at all
                        monthly = 16.20 if lb_type == "application" else 16.20  # ~$0.0225/hr
                        orphans.append({
                            "resource_id": lb_name,
                            "resource_type": f"Load Balancer ({lb_type})",
                            "category": "network",
                            "region": region,
                            "reason": "No target groups attached",
                            "age_days": age_days,
                            "monthly_cost": monthly,
                            "created": created.isoformat(),
                            "tags": {},
                            "cleanup_action": f"aws elbv2 delete-load-balancer --load-balancer-arn {lb_arn} --region {region}",
                            "confidence": "high",
                        })
                    else:
                        # Check if all targets are unhealthy or empty
                        all_empty = True
                        for tg in tgs:
                            health_resp, _ = safe_api_call(elbv2, "describe_target_health",
                                                           TargetGroupArn=tg["TargetGroupArn"])
                            targets = (health_resp or {}).get("TargetHealthDescriptions", [])
                            healthy = [t for t in targets
                                       if t.get("TargetHealth", {}).get("State") == "healthy"]
                            if healthy:
                                all_empty = False
                                break
                        if all_empty:
                            monthly = 16.20
                            orphans.append({
                                "resource_id": lb_name,
                                "resource_type": f"Load Balancer ({lb_type})",
                                "category": "network",
                                "region": region,
                                "reason": "Zero healthy targets across all target groups",
                                "age_days": age_days,
                                "monthly_cost": monthly,
                                "created": created.isoformat(),
                                "tags": {},
                                "cleanup_action": f"aws elbv2 delete-load-balancer --load-balancer-arn {lb_arn} --region {region}",
                                "confidence": "medium",
                            })
        except Exception as e:
            errors.append(f"ELB ({region}): {e}")

        if progress and task_id:
            progress.advance(task_id)

    return orphans, errors


def _check_nat_idle(cw, nat_id):
    """Check if a NAT Gateway has had zero traffic in the last 14 days."""
    try:
        end = datetime.now(timezone.utc)
        start = end.replace(day=max(1, end.day - 14))
        resp = cw.get_metric_statistics(
            Namespace="AWS/NATGateway",
            MetricName="BytesOutToDestination",
            Dimensions=[{"Name": "NatGatewayId", "Value": nat_id}],
            StartTime=start, EndTime=end,
            Period=86400, Statistics=["Sum"],
        )
        datapoints = resp.get("Datapoints", [])
        if not datapoints:
            return True
        total_bytes = sum(dp.get("Sum", 0) for dp in datapoints)
        return total_bytes == 0
    except Exception:
        return False
