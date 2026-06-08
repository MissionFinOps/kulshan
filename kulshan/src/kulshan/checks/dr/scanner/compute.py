"""Scan compute resilience: EC2 AZ spread, ASG config, ELB health."""

from datetime import datetime, timezone
from typing import Dict, List, Tuple
from collections import Counter
from ..utils.aws import safe_api_call, paginate_all


def scan_compute(session, regions, progress=None, task_id=None) -> Tuple[Dict, List[str]]:
    """Audit compute resilience across all regions."""
    findings = []
    errors = []
    stats = {
        "instances": 0,
        "multi_az_instances": False,
        "az_distribution": {},
        "asgs": [],
        "spof_asgs": [],
        "load_balancers": [],
        "single_az_lbs": [],
    }

    for region in regions:
        ec2 = session.client("ec2", region_name=region)

        # --- EC2 Instance AZ Distribution ---
        resp, err = safe_api_call(ec2, "describe_instances",
                                  Filters=[{"Name": "instance-state-name", "Values": ["running"]}])
        if err:
            errors.append(f"EC2 ({region}): {err}")
        else:
            az_counts = Counter()
            for res in (resp or {}).get("Reservations", []):
                for inst in res.get("Instances", []):
                    az = inst.get("Placement", {}).get("AvailabilityZone", "unknown")
                    az_counts[az] += 1
                    stats["instances"] += 1

            if az_counts:
                stats["az_distribution"][region] = dict(az_counts)
                if len(az_counts) > 1:
                    stats["multi_az_instances"] = True

            # SPOF: All instances in a single AZ
            if len(az_counts) == 1 and sum(az_counts.values()) > 1:
                az_name = list(az_counts.keys())[0]
                count = list(az_counts.values())[0]
                findings.append({
                    "category": "compute",
                    "severity": "high",
                    "title": f"All {count} instances in {region} are in a single AZ ({az_name})",
                    "detail": f"An AZ failure would take down all {count} running instances.",
                    "recommendation": "Spread instances across multiple AZs using an Auto Scaling Group.",
                })

        # --- Auto Scaling Groups ---
        try:
            asg_client = session.client("autoscaling", region_name=region)
            asgs, err = paginate_all(asg_client, "describe_auto_scaling_groups", "AutoScalingGroups")
            if err:
                errors.append(f"ASG ({region}): {err}")
            else:
                for asg in asgs:
                    name = asg["AutoScalingGroupName"]
                    min_size = asg.get("MinSize", 0)
                    max_size = asg.get("MaxSize", 0)
                    desired = asg.get("DesiredCapacity", 0)
                    azs = asg.get("AvailabilityZones", [])

                    asg_info = {
                        "name": name, "region": region,
                        "min": min_size, "max": max_size, "desired": desired,
                        "az_count": len(azs), "azs": azs,
                    }
                    stats["asgs"].append(asg_info)

                    # SPOF: min=max=1 (no scaling, no redundancy)
                    if min_size == max_size == 1:
                        stats["spof_asgs"].append(asg_info)
                        findings.append({
                            "category": "compute",
                            "severity": "high",
                            "title": f"ASG '{name}' has min=max=1 (no redundancy)",
                            "detail": "This ASG cannot scale and has a single point of failure.",
                            "recommendation": "Set min >= 2 across multiple AZs for production workloads.",
                        })

                    # Single AZ ASG
                    if len(azs) == 1 and desired > 0:
                        findings.append({
                            "category": "compute",
                            "severity": "medium",
                            "title": f"ASG '{name}' is in a single AZ ({azs[0]})",
                            "detail": f"All {desired} instance(s) would be lost in an AZ failure.",
                            "recommendation": "Add additional AZs to the ASG configuration.",
                        })
        except Exception as e:
            errors.append(f"ASG ({region}): {e}")

        # --- Load Balancers ---
        try:
            elbv2 = session.client("elbv2", region_name=region)
            lbs, err = paginate_all(elbv2, "describe_load_balancers", "LoadBalancers")
            if err:
                errors.append(f"ELB ({region}): {err}")
            else:
                for lb in lbs:
                    lb_name = lb.get("LoadBalancerName", "?")
                    lb_azs = [az["ZoneName"] for az in lb.get("AvailabilityZones", [])]
                    lb_info = {"name": lb_name, "region": region, "az_count": len(lb_azs), "azs": lb_azs}
                    stats["load_balancers"].append(lb_info)

                    if len(lb_azs) == 1:
                        stats["single_az_lbs"].append(lb_info)
                        findings.append({
                            "category": "compute",
                            "severity": "medium",
                            "title": f"Load balancer '{lb_name}' is in a single AZ",
                            "detail": f"Only in {lb_azs[0]}. No cross-AZ failover.",
                            "recommendation": "Add subnets in additional AZs.",
                        })
        except Exception as e:
            errors.append(f"ELB ({region}): {e}")

        if progress and task_id:
            progress.advance(task_id)

    return {"stats": stats, "findings": findings}, errors
