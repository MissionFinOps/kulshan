"""Scan for orphaned compute resources: EBS volumes, EIPs, snapshots, AMIs, ENIs, key pairs."""

from datetime import datetime, timezone
from typing import Dict, List, Tuple
from ..utils.aws import safe_api_call, paginate_all


def scan_compute(session, regions, progress=None, task_id=None) -> Tuple[List[Dict], List[str]]:
    """Find orphaned compute resources across all regions."""
    orphans = []
    errors = []

    for region in regions:
        ec2 = session.client("ec2", region_name=region)

        # --- Unattached EBS Volumes ---
        resp, err = safe_api_call(ec2, "describe_volumes",
                                  Filters=[{"Name": "status", "Values": ["available"]}])
        if err:
            errors.append(f"EBS ({region}): {err}")
        else:
            for vol in resp.get("Volumes", []):
                created = vol.get("CreateTime", datetime.now(timezone.utc))
                age_days = (datetime.now(timezone.utc) - created).days
                size_gb = vol.get("Size", 0)
                vol_type = vol.get("VolumeType", "gp2")
                monthly = _ebs_monthly_cost(size_gb, vol_type)
                orphans.append({
                    "resource_id": vol["VolumeId"],
                    "resource_type": "EBS Volume",
                    "category": "compute",
                    "region": region,
                    "reason": f"Unattached ({vol_type}, {size_gb} GB)",
                    "age_days": age_days,
                    "monthly_cost": monthly,
                    "created": created.isoformat(),
                    "tags": {t["Key"]: t["Value"] for t in vol.get("Tags", [])},
                    "cleanup_action": f"aws ec2 delete-volume --volume-id {vol['VolumeId']} --region {region}",
                    "confidence": "high",
                })

        # --- Unused Elastic IPs ---
        resp, err = safe_api_call(ec2, "describe_addresses")
        if err:
            errors.append(f"EIP ({region}): {err}")
        else:
            for addr in resp.get("Addresses", []):
                if not addr.get("AssociationId"):
                    alloc_id = addr.get("AllocationId", "?")
                    orphans.append({
                        "resource_id": alloc_id,
                        "resource_type": "Elastic IP",
                        "category": "compute",
                        "region": region,
                        "reason": f"Not associated ({addr.get('PublicIp', '?')})",
                        "age_days": None,
                        "monthly_cost": 3.65,  # ~$0.005/hr
                        "created": None,
                        "tags": {t["Key"]: t["Value"] for t in addr.get("Tags", [])},
                        "cleanup_action": f"aws ec2 release-address --allocation-id {alloc_id} --region {region}",
                        "confidence": "high",
                    })

        # --- Orphaned Snapshots (source volume deleted) ---
        snaps, err = paginate_all(ec2, "describe_snapshots", "Snapshots", OwnerIds=["self"])
        if err:
            errors.append(f"Snapshots ({region}): {err}")
        else:
            # Get current volume IDs to check if source still exists
            vols_resp, _ = safe_api_call(ec2, "describe_volumes")
            live_vol_ids = {v["VolumeId"] for v in (vols_resp or {}).get("Volumes", [])}

            for snap in snaps:
                src_vol = snap.get("VolumeId", "")
                if src_vol and src_vol not in live_vol_ids:
                    created = snap.get("StartTime", datetime.now(timezone.utc))
                    age_days = (datetime.now(timezone.utc) - created).days
                    size_gb = snap.get("VolumeSize", 0)
                    monthly = size_gb * 0.05  # $0.05/GB-month for snapshots
                    orphans.append({
                        "resource_id": snap["SnapshotId"],
                        "resource_type": "EBS Snapshot",
                        "category": "compute",
                        "region": region,
                        "reason": f"Source volume {src_vol} deleted ({size_gb} GB)",
                        "age_days": age_days,
                        "monthly_cost": monthly,
                        "created": created.isoformat(),
                        "tags": {t["Key"]: t["Value"] for t in snap.get("Tags", [])},
                        "cleanup_action": f"aws ec2 delete-snapshot --snapshot-id {snap['SnapshotId']} --region {region}",
                        "confidence": "medium",
                    })

        # --- Unused AMIs (not used by any running instance) ---
        images_resp, err = safe_api_call(ec2, "describe_images", Owners=["self"])
        if err:
            errors.append(f"AMI ({region}): {err}")
        else:
            instances_resp, _ = safe_api_call(ec2, "describe_instances")
            active_amis = set()
            for res in (instances_resp or {}).get("Reservations", []):
                for inst in res.get("Instances", []):
                    active_amis.add(inst.get("ImageId"))

            for img in (images_resp or {}).get("Images", []):
                if img["ImageId"] not in active_amis:
                    created = img.get("CreationDate", "")
                    age_days = None
                    if created:
                        try:
                            dt = datetime.fromisoformat(created.replace("Z", "+00:00"))
                            age_days = (datetime.now(timezone.utc) - dt).days
                        except Exception:
                            pass
                    orphans.append({
                        "resource_id": img["ImageId"],
                        "resource_type": "AMI",
                        "category": "compute",
                        "region": region,
                        "reason": f"Not used by any instance ({img.get('Name', 'unnamed')})",
                        "age_days": age_days,
                        "monthly_cost": 0,  # AMIs are free, but their snapshots cost
                        "created": created or None,
                        "tags": {t["Key"]: t["Value"] for t in img.get("Tags", [])},
                        "cleanup_action": f"aws ec2 deregister-image --image-id {img['ImageId']} --region {region}",
                        "confidence": "low",
                    })

        # --- Detached ENIs ---
        resp, err = safe_api_call(ec2, "describe_network_interfaces",
                                  Filters=[{"Name": "status", "Values": ["available"]}])
        if err:
            errors.append(f"ENI ({region}): {err}")
        else:
            for eni in resp.get("NetworkInterfaces", []):
                # Skip ENIs managed by AWS services
                requester = eni.get("RequesterId", "")
                if requester and requester != "":
                    desc = eni.get("Description", "").lower()
                    if any(svc in desc for svc in ["efs", "elb", "lambda", "nat", "rds", "vpce"]):
                        continue
                orphans.append({
                    "resource_id": eni["NetworkInterfaceId"],
                    "resource_type": "Network Interface",
                    "category": "compute",
                    "region": region,
                    "reason": f"Detached ({eni.get('Description', 'no description')[:60]})",
                    "age_days": None,
                    "monthly_cost": 0,
                    "created": None,
                    "tags": {t["Key"]: t["Value"] for t in eni.get("TagSet", [])},
                    "cleanup_action": f"aws ec2 delete-network-interface --network-interface-id {eni['NetworkInterfaceId']} --region {region}",
                    "confidence": "medium",
                })

        if progress and task_id:
            progress.advance(task_id)

    return orphans, errors


def _ebs_monthly_cost(size_gb, vol_type):
    """Estimate monthly cost for an EBS volume."""
    rates = {
        "gp2": 0.10, "gp3": 0.08, "io1": 0.125, "io2": 0.125,
        "st1": 0.045, "sc1": 0.015, "standard": 0.05,
    }
    return size_gb * rates.get(vol_type, 0.10)
