"""Scan for orphaned network resources: unused SGs, idle NAT GWs, idle LBs."""

from datetime import datetime, timezone
from typing import Dict, List, Tuple
from ..utils.aws import safe_api_call, paginate_all
from .evidence import activity_evidence, qualify_findings


def scan_network(session, regions, progress=None, task_id=None) -> Tuple[List[Dict], List[str]]:
    """Find orphaned network resources across all regions."""
    orphans = []
    errors = []

    for region in regions:
        try:
            ec2 = session.client("ec2", region_name=region)

            # --- Unused Security Groups ---
            resp, err = safe_api_call(ec2, "describe_security_groups")
            if err:
                errors.append(f"SG ({region}): {err}")
            else:
                # Find all SGs referenced by ENIs
                eni_resp, eni_err = safe_api_call(ec2, "describe_network_interfaces")
                if eni_err:
                    errors.append(f"ec2.describe_network_interfaces ({region}): {eni_err}")
                used_sgs = set()
                for eni in (eni_resp or {}).get("NetworkInterfaces", []):
                    for g in eni.get("Groups", []):
                        used_sgs.add(g["GroupId"])

                for sg in [] if eni_err else resp["SecurityGroups"]:
                    if sg["GroupName"] == "default":
                        continue
                    if sg["GroupId"] not in used_sgs:
                        orphans.append(
                            {
                                "resource_id": sg["GroupId"],
                                "resource_type": "Security Group",
                                "category": "network",
                                "region": region,
                                "reason": f"Not attached to any resource ({sg['GroupName']})",
                                "age_days": None,
                                "monthly_cost": None,
                                "created": None,
                                "tags": {t["Key"]: t["Value"] for t in sg.get("Tags", [])},
                                "cleanup_action": f"aws ec2 delete-security-group --group-id {sg['GroupId']} --region {region}",
                                "confidence": "medium",
                            }
                        )

            # --- Idle NAT Gateways ---
            resp, err = safe_api_call(
                ec2, "describe_nat_gateways", Filters=[{"Name": "state", "Values": ["available"]}]
            )
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
                    if idle["status"] != "confirmed_observation":
                        errors.append(
                            f"cloudwatch.GetMetricStatistics ({region}): "
                            f"{idle['missing_data_reason']}"
                        )
                    if idle["idle"] is not False:
                        orphans.append(
                            {
                                "resource_id": nat_id,
                                "resource_type": "NAT Gateway",
                                "category": "network",
                                "region": region,
                                "reason": "NAT metric observation: " + idle["status"],
                                "status": idle["status"],
                                "evidence": idle,
                                "age_days": age_days,
                                "monthly_cost": None,
                                "created": created.isoformat(),
                                "tags": {t["Key"]: t["Value"] for t in nat.get("Tags", [])},
                                "cleanup_action": f"aws ec2 delete-nat-gateway --nat-gateway-id {nat_id} --region {region}",
                                "confidence": "high",
                            }
                        )

        except Exception as exc:
            errors.append(f"network ({region}): incomplete check: {exc}")

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
                    tg_resp, tg_err = safe_api_call(
                        elbv2, "describe_target_groups", LoadBalancerArn=lb_arn
                    )
                    if tg_err:
                        errors.append(f"elbv2.describe_target_groups ({region}): {tg_err}")
                        continue
                    tgs = tg_resp["TargetGroups"]

                    if not tgs:
                        # LB with no target groups at all

                        orphans.append(
                            {
                                "resource_id": lb_name,
                                "resource_type": f"Load Balancer ({lb_type})",
                                "category": "network",
                                "region": region,
                                "reason": "No target groups attached",
                                "age_days": age_days,
                                "monthly_cost": None,
                                "created": created.isoformat(),
                                "tags": {},
                                "cleanup_action": f"aws elbv2 delete-load-balancer --load-balancer-arn {lb_arn} --region {region}",
                                "confidence": "high",
                            }
                        )
                    else:
                        # Check if all targets are unhealthy or empty
                        all_empty = True
                        for tg in tgs:
                            health_resp, health_err = safe_api_call(
                                elbv2, "describe_target_health", TargetGroupArn=tg["TargetGroupArn"]
                            )
                            if health_err:
                                errors.append(
                                    f"elbv2.describe_target_health ({region}): {health_err}"
                                )
                                all_empty = False
                                break
                            targets = health_resp["TargetHealthDescriptions"]
                            healthy = [
                                t
                                for t in targets
                                if t.get("TargetHealth", {}).get("State") == "healthy"
                            ]
                            if healthy:
                                all_empty = False
                                break
                        if all_empty:
                            orphans.append(
                                {
                                    "resource_id": lb_name,
                                    "resource_type": f"Load Balancer ({lb_type})",
                                    "category": "network",
                                    "region": region,
                                    "reason": "Zero healthy targets across all target groups",
                                    "age_days": age_days,
                                    "monthly_cost": None,
                                    "created": created.isoformat(),
                                    "tags": {},
                                    "cleanup_action": f"aws elbv2 delete-load-balancer --load-balancer-arn {lb_arn} --region {region}",
                                    "confidence": "medium",
                                }
                            )
        except Exception as e:
            errors.append(f"ELB ({region}): {e}")

        if progress and task_id:
            progress.advance(task_id)

    return qualify_findings(orphans), errors


def _check_nat_idle(cw, resource_id, *, now=None):
    """Return validated rolling-window activity evidence."""
    return activity_evidence(
        cw, "AWS/NATGateway", "BytesOutToDestination", "NatGatewayId", resource_id, 14, now
    )
