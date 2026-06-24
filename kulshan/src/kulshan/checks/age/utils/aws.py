"""AWS session, retry, and pagination helpers."""
from __future__ import annotations

import boto3

from kulshan.aws_runtime import client, paginate_all, safe_api_call


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