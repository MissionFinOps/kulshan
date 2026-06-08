"""AWS session, retry, and pagination helpers."""

import boto3
import botocore
import time
from typing import Any, Dict, List, Optional, Tuple


def get_session(profile=None, role_arn=None):
    session = boto3.Session(profile_name=profile)
    if role_arn:
        sts = session.client("sts")
        creds = sts.assume_role(RoleArn=role_arn, RoleSessionName="Kulshan-dr-scan")["Credentials"]
        session = boto3.Session(
            aws_access_key_id=creds["AccessKeyId"],
            aws_secret_access_key=creds["SecretAccessKey"],
            aws_session_token=creds["SessionToken"],
        )
    return session


def get_account_info(session):
    sts = session.client("sts")
    identity = sts.get_caller_identity()
    return {"account_id": identity["Account"], "arn": identity["Arn"]}


def get_enabled_regions(session):
    ec2 = session.client("ec2", region_name="us-east-1")
    try:
        regions = ec2.describe_regions(
            Filters=[{"Name": "opt-in-status", "Values": ["opt-in-not-required", "opted-in"]}])
        return sorted([r["RegionName"] for r in regions["Regions"]])
    except Exception:
        return ["us-east-1", "us-west-2", "eu-west-1"]


def safe_api_call(client, method, **kwargs):
    retries = 3
    for attempt in range(retries):
        try:
            result = getattr(client, method)(**kwargs)
            if isinstance(result, dict):
                result.pop("ResponseMetadata", None)
            return result, None
        except botocore.exceptions.ClientError as e:
            code = e.response["Error"]["Code"]
            if code in ("Throttling", "TooManyRequestsException", "RequestLimitExceeded"):
                time.sleep(2 ** attempt)
                continue
            if code in ("AccessDeniedException", "AccessDenied"):
                return None, f"Access denied: {method}"
            return None, f"{code}: {e.response['Error']['Message']}"
        except botocore.exceptions.EndpointConnectionError:
            return None, "Region not available"
        except Exception as e:
            return None, str(e)
    return None, "Max retries exceeded"


def paginate_all(client, method, key, **kwargs):
    results = []
    try:
        paginator = client.get_paginator(method)
        for page in paginator.paginate(**kwargs):
            results.extend(page.get(key, []))
    except Exception as e:
        return results, str(e)
    return results, None
