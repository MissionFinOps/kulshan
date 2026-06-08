"""Single Point of Failure (SPOF) detector across all resource types."""

from typing import Dict, List, Tuple
from ..utils.aws import safe_api_call


def scan_spof(session, regions, progress=None, task_id=None) -> Tuple[Dict, List[str]]:
    """Detect single points of failure across the account."""
    findings = []
    errors = []
    spofs = []

    for region in regions:
        ec2 = session.client("ec2", region_name=region)

        # --- Single NAT Gateway per VPC ---
        nat_resp, err = safe_api_call(ec2, "describe_nat_gateways",
                                       Filters=[{"Name": "state", "Values": ["available"]}])
        if err:
            errors.append(f"NAT GW SPOF ({region}): {err}")
        else:
            # Group NAT GWs by VPC
            vpc_nats = {}
            for nat in (nat_resp or {}).get("NatGateways", []):
                vpc_id = nat.get("VpcId", "?")
                if vpc_id not in vpc_nats:
                    vpc_nats[vpc_id] = []
                vpc_nats[vpc_id].append(nat)

            for vpc_id, nats in vpc_nats.items():
                if len(nats) == 1:
                    nat = nats[0]
                    az = nat.get("SubnetId", "?")
                    # Count instances in this VPC to estimate blast radius
                    inst_resp, _ = safe_api_call(ec2, "describe_instances",
                                                  Filters=[
                                                      {"Name": "vpc-id", "Values": [vpc_id]},
                                                      {"Name": "instance-state-name", "Values": ["running"]},
                                                  ])
                    instance_count = sum(
                        len(r.get("Instances", []))
                        for r in (inst_resp or {}).get("Reservations", [])
                    )

                    spof = {
                        "resource_type": "NAT Gateway",
                        "resource_id": nat["NatGatewayId"],
                        "region": region,
                        "detail": f"Single NAT GW in VPC {vpc_id}",
                        "blast_radius": f"{instance_count} running instances lose outbound internet",
                    }
                    spofs.append(spof)
                    if instance_count > 0:
                        findings.append({
                            "category": "spof",
                            "severity": "high" if instance_count > 10 else "medium",
                            "title": f"Single NAT Gateway in VPC {vpc_id} ({region})",
                            "detail": f"If {nat['NatGatewayId']} fails, {instance_count} instances lose outbound traffic.",
                            "recommendation": "Deploy NAT Gateways in multiple AZs for redundancy.",
                        })

        # --- Single-instance RDS (non-Multi-AZ already caught by database scanner,
        #     but we flag the blast radius here) ---

        # --- Single Bastion / Jump Host ---
        inst_resp, err = safe_api_call(ec2, "describe_instances",
                                        Filters=[
                                            {"Name": "instance-state-name", "Values": ["running"]},
                                            {"Name": "tag:Name", "Values": ["*bastion*", "*jump*", "*Bastion*", "*Jump*"]},
                                        ])
        if not err:
            bastion_count = sum(
                len(r.get("Instances", []))
                for r in (inst_resp or {}).get("Reservations", [])
            )
            if bastion_count == 1:
                spof = {
                    "resource_type": "Bastion Host",
                    "resource_id": "single-bastion",
                    "region": region,
                    "detail": "Only 1 bastion/jump host found",
                    "blast_radius": "All SSH/RDP access to private subnets lost",
                }
                spofs.append(spof)
                findings.append({
                    "category": "spof",
                    "severity": "medium",
                    "title": f"Single bastion host in {region}",
                    "detail": "If the bastion fails, remote access to private resources is lost.",
                    "recommendation": "Use SSM Session Manager or deploy redundant bastion hosts.",
                })

        if progress and task_id:
            progress.advance(task_id)

    return {"spofs": spofs, "findings": findings}, errors
