"""AWS session, region discovery, and parallel API call helpers."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Dict, List, Optional

import boto3

from kulshan.aws_runtime import client, safe_api_call


def get_session(profile: Optional[str] = None, role_arn: Optional[str] = None) -> boto3.Session:
    """Get boto3 session using default credential chain."""
    session = boto3.Session(profile_name=profile)
    if role_arn:
        sts = client(session, "sts")
        creds = sts.assume_role(RoleArn=role_arn, RoleSessionName="kulshan-security-scan")["Credentials"]
        session = boto3.Session(
            aws_access_key_id=creds["AccessKeyId"],
            aws_secret_access_key=creds["SecretAccessKey"],
            aws_session_token=creds["SessionToken"],
        )
    return session


def get_account_info(session: boto3.Session) -> Dict[str, str]:
    """Get current account ID and caller identity."""
    sts = client(session, "sts")
    identity = sts.get_caller_identity()
    return {
        "account_id": identity["Account"],
        "arn": identity["Arn"],
        "user_id": identity["UserId"],
    }


def get_enabled_regions(session: boto3.Session) -> List[str]:
    """Get all enabled regions for this account."""
    ec2 = client(session, "ec2", region_name="us-east-1")
    try:
        regions = ec2.describe_regions(
            Filters=[{"Name": "opt-in-status", "Values": ["opt-in-not-required", "opted-in"]}]
        )
        return sorted([r["RegionName"] for r in regions["Regions"]])
    except Exception:
        return [
            "us-east-1", "us-east-2", "us-west-1", "us-west-2",
            "eu-west-1", "eu-central-1", "ap-southeast-1",
        ]


def parallel_collect(tasks: List[Dict], session: boto3.Session, progress=None, task_id=None) -> Dict[str, Any]:
    """Run multiple API collection tasks in parallel.

    Each task: {"key": str, "service": str, "region": str, "method": str, "kwargs": dict}
    Returns: {key: (data, error)}
    """
    results = {}

    def _run(task):
        aws_client = client(session, task["service"], region_name=task["region"])
        data, err = safe_api_call(aws_client, task["method"], **task.get("kwargs", {}))
        return task["key"], data, err

    with ThreadPoolExecutor(max_workers=20) as executor:
        futures = {executor.submit(_run, t): t for t in tasks}
        for future in as_completed(futures):
            key, data, err = future.result()
            results[key] = (data, err)
            if progress and task_id:
                progress.advance(task_id)

    return results