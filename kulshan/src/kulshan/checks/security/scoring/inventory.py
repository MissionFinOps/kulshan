"""Resource inventory summary."""

from typing import Dict, Any


def build_inventory(resources: Dict[str, Any]) -> Dict:
    """Build a resource count summary from scan data."""
    inv = {}

    # IAM
    iam = resources.get("iam", {})
    inv["IAM Users"] = len(iam.get("users", []))
    inv["IAM Roles"] = len(iam.get("roles", []))
    inv["IAM Groups"] = len(iam.get("groups", []))
    inv["IAM Policies"] = len(iam.get("policies", []))

    # Network
    net = resources.get("network", {})
    inv["VPCs"] = len(net.get("vpcs", []))
    inv["Security Groups"] = len(net.get("security_groups", []))
    inv["Subnets"] = len(net.get("subnets", []))

    # Data
    data = resources.get("data", {})
    inv["S3 Buckets"] = len(data.get("s3_buckets", []))

    # Filter out zeros
    return {k: v for k, v in inv.items() if v > 0}
