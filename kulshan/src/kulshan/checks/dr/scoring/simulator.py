"""Disaster scenario simulator, estimates recovery time, data loss, and cost."""

from typing import Dict, List
from ..utils.aws import safe_api_call


def simulate_az_failure(session, region, target_az=None) -> Dict:
    """Simulate an AZ failure and estimate impact."""
    ec2 = session.client("ec2", region_name=region)

    # Get AZs
    if not target_az:
        az_resp, _ = safe_api_call(ec2, "describe_availability_zones",
                                    Filters=[{"Name": "state", "Values": ["available"]}])
        azs = [az["ZoneName"] for az in (az_resp or {}).get("AvailabilityZones", [])]
        target_az = azs[0] if azs else f"{region}a"

    impact = {
        "scenario": f"AZ Failure: {target_az}",
        "region": region,
        "target_az": target_az,
        "affected_instances": 0,
        "affected_rds": 0,
        "affected_elbs": 0,
        "affected_nat_gws": 0,
        "recovery_steps": [],
        "estimated_recovery_minutes": 0,
        "data_at_risk_gb": 0,
    }

    # EC2 instances in the target AZ
    inst_resp, _ = safe_api_call(ec2, "describe_instances",
                                  Filters=[
                                      {"Name": "availability-zone", "Values": [target_az]},
                                      {"Name": "instance-state-name", "Values": ["running"]},
                                  ])
    for res in (inst_resp or {}).get("Reservations", []):
        impact["affected_instances"] += len(res.get("Instances", []))

    if impact["affected_instances"] > 0:
        impact["recovery_steps"].append({
            "step": "Relaunch EC2 instances in healthy AZ",
            "estimated_minutes": max(15, impact["affected_instances"] * 3),
        })

    # RDS in the target AZ
    rds = session.client("rds", region_name=region)
    rds_resp, _ = safe_api_call(rds, "describe_db_instances")
    for db in (rds_resp or {}).get("DBInstances", []):
        az = db.get("AvailabilityZone", "")
        if az == target_az:
            impact["affected_rds"] += 1
            storage = db.get("AllocatedStorage", 0)
            impact["data_at_risk_gb"] += storage
            multi_az = db.get("MultiAZ", False)
            if multi_az:
                impact["recovery_steps"].append({
                    "step": f"RDS '{db['DBInstanceIdentifier']}' Multi-AZ failover (automatic)",
                    "estimated_minutes": 5,
                })
            else:
                impact["recovery_steps"].append({
                    "step": f"RDS '{db['DBInstanceIdentifier']}' restore from snapshot (MANUAL)",
                    "estimated_minutes": max(30, storage // 10),
                })

    # NAT Gateways in the target AZ
    nat_resp, _ = safe_api_call(ec2, "describe_nat_gateways",
                                 Filters=[{"Name": "state", "Values": ["available"]}])
    for nat in (nat_resp or {}).get("NatGateways", []):
        # Check subnet AZ
        subnet_id = nat.get("SubnetId", "")
        if subnet_id:
            sub_resp, _ = safe_api_call(ec2, "describe_subnets", SubnetIds=[subnet_id])
            for sub in (sub_resp or {}).get("Subnets", []):
                if sub.get("AvailabilityZone") == target_az:
                    impact["affected_nat_gws"] += 1

    if impact["affected_nat_gws"] > 0:
        impact["recovery_steps"].append({
            "step": "Create replacement NAT Gateway in healthy AZ + update route tables",
            "estimated_minutes": 10,
        })

    # DNS failover
    impact["recovery_steps"].insert(0, {
        "step": "DNS failover (if configured)",
        "estimated_minutes": 5,
    })

    # Total estimated recovery
    impact["estimated_recovery_minutes"] = sum(
        s["estimated_minutes"] for s in impact["recovery_steps"]
    )

    return impact


def simulate_region_failure(session, region) -> Dict:
    """Simulate a full region failure and estimate impact."""
    ec2 = session.client("ec2", region_name=region)

    impact = {
        "scenario": f"Region Failure: {region}",
        "region": region,
        "affected_instances": 0,
        "affected_rds": 0,
        "affected_s3_buckets": 0,
        "recovery_steps": [],
        "estimated_recovery_minutes": 0,
        "data_at_risk_gb": 0,
        "cross_region_resources": False,
    }

    # All running instances
    inst_resp, _ = safe_api_call(ec2, "describe_instances",
                                  Filters=[{"Name": "instance-state-name", "Values": ["running"]}])
    for res in (inst_resp or {}).get("Reservations", []):
        impact["affected_instances"] += len(res.get("Instances", []))

    # All RDS
    rds = session.client("rds", region_name=region)
    rds_resp, _ = safe_api_call(rds, "describe_db_instances")
    for db in (rds_resp or {}).get("DBInstances", []):
        impact["affected_rds"] += 1
        impact["data_at_risk_gb"] += db.get("AllocatedStorage", 0)

    # S3 buckets (check for cross-region replication)
    s3 = session.client("s3", region_name="us-east-1")
    buckets_resp, _ = safe_api_call(s3, "list_buckets")
    for bucket in (buckets_resp or {}).get("Buckets", []):
        try:
            loc_resp = s3.get_bucket_location(Bucket=bucket["Name"])
            loc = loc_resp.get("LocationConstraint") or "us-east-1"
            if loc == region:
                impact["affected_s3_buckets"] += 1
                rep_resp, _ = safe_api_call(s3, "get_bucket_replication", Bucket=bucket["Name"])
                if rep_resp and rep_resp.get("ReplicationConfiguration", {}).get("Rules"):
                    impact["cross_region_resources"] = True
        except Exception:
            pass

    # Recovery steps
    if impact["affected_instances"] > 0:
        impact["recovery_steps"].append({
            "step": f"Rebuild {impact['affected_instances']} instances in DR region from AMIs/IaC",
            "estimated_minutes": max(60, impact["affected_instances"] * 5),
        })

    if impact["affected_rds"] > 0:
        impact["recovery_steps"].append({
            "step": f"Restore {impact['affected_rds']} databases from cross-region snapshots",
            "estimated_minutes": max(60, impact["data_at_risk_gb"] // 5),
        })

    impact["recovery_steps"].append({
        "step": "Update DNS to point to DR region",
        "estimated_minutes": 10,
    })

    impact["recovery_steps"].append({
        "step": "Validate application health in DR region",
        "estimated_minutes": 30,
    })

    impact["estimated_recovery_minutes"] = sum(
        s["estimated_minutes"] for s in impact["recovery_steps"]
    )

    return impact
