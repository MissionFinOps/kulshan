"""AWS session, retry, and pagination helpers."""

from __future__ import annotations

import boto3

from kulshan.aws_runtime import client
from kulshan.aws_runtime import safe_api_call as runtime_call


def get_session(profile=None, role_arn=None):
    session = boto3.Session(profile_name=profile)
    if role_arn:
        sts = client(session, "sts")
        creds = sts.assume_role(RoleArn=role_arn, RoleSessionName="kulshan-scan")["Credentials"]
        session = boto3.Session(
            aws_access_key_id=creds["AccessKeyId"],
            aws_secret_access_key=creds["SecretAccessKey"],
            aws_session_token=creds["SessionToken"],
        )
    return session


def get_account_info(session):
    sts = client(session, "sts")
    identity = sts.get_caller_identity()
    return {"account_id": identity["Account"], "arn": identity["Arn"]}


def get_enabled_regions(session):
    ec2 = client(session, "ec2", region_name="us-east-1")
    try:
        regions = ec2.describe_regions(
            Filters=[{"Name": "opt-in-status", "Values": ["opt-in-not-required", "opted-in"]}]
        )
        return sorted([r["RegionName"] for r in regions["Regions"]])
    except Exception:
        return ["us-east-1", "us-west-2", "eu-west-1"]


# Sweep inventories must distinguish a validated empty list from unavailable data.
_INVENTORIES = {
    "describe_security_groups": "SecurityGroups",
    "describe_network_interfaces": "NetworkInterfaces",
    "describe_nat_gateways": "NatGateways",
    "describe_target_groups": "TargetGroups",
    "describe_target_health": "TargetHealthDescriptions",
    "describe_volumes": "Volumes",
    "describe_addresses": "Addresses",
    "describe_images": "Images",
    "describe_instances": "Reservations",
    "list_buckets": "Buckets",
    "describe_repositories": "repositories",
    "list_images": "imageIds",
}


def paginate_all(client_obj, method, key, **kwargs):
    """Reject incomplete pagination and malformed inventories without empty success."""
    items = []
    try:
        paginator = client_obj.get_paginator(method)
        pages = 0
        for page in paginator.paginate(**kwargs):
            pages += 1
            if not isinstance(page, dict) or not isinstance(page.get(key), list):
                return [], f"{method}: malformed response (missing list {key})"
            if not _valid_items(method, page[key]):
                return [], f"{method}: malformed inventory entries"
            items.extend(page[key])
        if not pages:
            return [], f"{method}: no response pages"
    except Exception as exc:
        return [], f"{method}: {exc} (inventory incomplete)"
    return items, None


def safe_api_call(client_obj, method, **kwargs):
    """Read all inventory pages when supported and validate successful responses."""
    key = _INVENTORIES.get(method)
    if key:
        try:
            paginated = client_obj.can_paginate(method)
        except Exception as exc:
            return None, f"{method}: cannot determine pagination: {exc}"
        if paginated:
            items, error = paginate_all(client_obj, method, key, **kwargs)
            return ({key: items} if error is None else None), error
    response, error = runtime_call(client_obj, method, **kwargs)
    if error:
        return None, f"{method}: {error}"
    if not isinstance(response, dict) or (
        key and (not isinstance(response.get(key), list) or not _valid_items(method, response[key]))
    ):
        return None, f"{method}: malformed response"
    if any(response.get(token) for token in ("NextToken", "nextToken", "NextMarker", "Marker")):
        return None, f"{method}: incomplete pagination"
    return response, None


_REQUIRED = {
    "describe_security_groups": ("GroupId", "GroupName"),
    "describe_network_interfaces": ("NetworkInterfaceId", "Groups"),
    "describe_nat_gateways": ("NatGatewayId",),
    "describe_target_groups": ("TargetGroupArn",),
    "describe_target_health": ("TargetHealth",),
    "describe_volumes": ("VolumeId",),
    "describe_addresses": ("PublicIp",),
    "describe_images": ("ImageId",),
    "describe_instances": ("Instances",),
    "describe_snapshots": ("SnapshotId", "VolumeId"),
    "describe_load_balancers": ("LoadBalancerArn",),
    "describe_log_groups": ("logGroupName", "storedBytes"),
    "describe_alarms": ("AlarmName", "StateUpdatedTimestamp"),
    "list_functions": ("FunctionName",),
    "list_buckets": ("Name",),
    "describe_repositories": ("repositoryName",),
    "describe_db_snapshots": ("DBSnapshotIdentifier", "SnapshotCreateTime"),
    "describe_db_instances": ("DBInstanceIdentifier", "DBInstanceStatus"),
}


def _valid_items(method, items):
    for item in items:
        if not isinstance(item, dict) or any(
            item.get(field) is None for field in _REQUIRED.get(method, ())
        ):
            return False
        if method == "describe_network_interfaces" and (
            not isinstance(item["Groups"], list)
            or any(
                not isinstance(group, dict) or not group.get("GroupId") for group in item["Groups"]
            )
        ):
            return False
        if method == "describe_instances" and (
            not isinstance(item["Instances"], list)
            or any(
                not isinstance(instance, dict) or not instance.get("ImageId")
                for instance in item["Instances"]
            )
        ):
            return False
        if method == "describe_target_health":
            health = item["TargetHealth"]
            if not isinstance(health, dict) or health.get("State") not in {
                "healthy",
                "unhealthy",
                "unused",
                "initial",
                "draining",
                "unavailable",
            }:
                return False
    return True
