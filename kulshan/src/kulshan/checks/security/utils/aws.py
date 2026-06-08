"""AWS session, region discovery, and parallel API call helpers."""

import boto3
import botocore
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Callable, Dict, List, Optional, Tuple
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TimeElapsedColumn
import time
import json
import os
import hashlib

CACHE_DIR = os.path.join(os.path.expanduser("~"), ".Kulshan", "security", "cache")
CACHE_TTL = 3600  # 1 hour


def get_session(profile: Optional[str] = None, role_arn: Optional[str] = None) -> boto3.Session:
    """Get boto3 session using default credential chain."""
    session = boto3.Session(profile_name=profile)
    if role_arn:
        sts = session.client("sts")
        creds = sts.assume_role(RoleArn=role_arn, RoleSessionName="Kulshan-security-scan")["Credentials"]
        session = boto3.Session(
            aws_access_key_id=creds["AccessKeyId"],
            aws_secret_access_key=creds["SecretAccessKey"],
            aws_session_token=creds["SessionToken"],
        )
    return session


def get_account_info(session: boto3.Session) -> Dict[str, str]:
    """Get current account ID and caller identity."""
    sts = session.client("sts")
    identity = sts.get_caller_identity()
    return {
        "account_id": identity["Account"],
        "arn": identity["Arn"],
        "user_id": identity["UserId"],
    }


def get_enabled_regions(session: boto3.Session) -> List[str]:
    """Get all enabled regions for this account."""
    ec2 = session.client("ec2", region_name="us-east-1")
    try:
        regions = ec2.describe_regions(
            Filters=[{"Name": "opt-in-status", "Values": ["opt-in-not-required", "opted-in"]}]
        )
        return sorted([r["RegionName"] for r in regions["Regions"]])
    except Exception:
        return ["us-east-1", "us-east-2", "us-west-1", "us-west-2", "eu-west-1", "eu-central-1", "ap-southeast-1"]


def _cache_key(service: str, call: str, region: str, **kwargs) -> str:
    raw = f"{service}:{call}:{region}:{json.dumps(kwargs, sort_keys=True, default=str)}"
    return hashlib.md5(raw.encode()).hexdigest()


def _get_cached(key: str) -> Optional[Any]:
    path = os.path.join(CACHE_DIR, f"{key}.json")
    if os.path.exists(path):
        mtime = os.path.getmtime(path)
        if time.time() - mtime < CACHE_TTL:
            with open(path) as f:
                return json.load(f)
    return None


def _set_cache(key: str, data: Any):
    os.makedirs(CACHE_DIR, exist_ok=True)
    path = os.path.join(CACHE_DIR, f"{key}.json")
    try:
        with open(path, "w") as f:
            json.dump(data, f, default=str)
    except Exception:
        pass


def safe_api_call(client, method: str, use_cache: bool = True, **kwargs) -> Tuple[Any, Optional[str]]:
    """Make an API call with error handling, retry, and caching."""
    if use_cache:
        ck = _cache_key(client.meta.service_model.service_name, method, client.meta.region_name, **kwargs)
        cached = _get_cached(ck)
        if cached is not None:
            return cached, None

    retries = 3
    for attempt in range(retries):
        try:
            fn = getattr(client, method)
            result = fn(**kwargs)
            # Remove ResponseMetadata to keep cache clean
            if isinstance(result, dict):
                result.pop("ResponseMetadata", None)
            if use_cache:
                _set_cache(ck, result)
            return result, None
        except botocore.exceptions.ClientError as e:
            code = e.response["Error"]["Code"]
            if code in ("Throttling", "TooManyRequestsException", "RequestLimitExceeded"):
                time.sleep(2 ** attempt)
                continue
            if code in ("AccessDeniedException", "AccessDenied", "UnauthorizedAccess"):
                return None, f"Access denied: {method}"
            return None, f"{code}: {e.response['Error']['Message']}"
        except botocore.exceptions.EndpointConnectionError:
            return None, f"Region not available"
        except Exception as e:
            return None, str(e)
    return None, "Max retries exceeded"


def parallel_collect(tasks: List[Dict], session: boto3.Session, progress=None, task_id=None) -> Dict[str, Any]:
    """Run multiple API collection tasks in parallel.
    
    Each task: {"key": str, "service": str, "region": str, "method": str, "kwargs": dict}
    Returns: {key: (data, error)}
    """
    results = {}
    
    def _run(task):
        client = session.client(task["service"], region_name=task["region"])
        data, err = safe_api_call(client, task["method"], **task.get("kwargs", {}))
        return task["key"], data, err

    with ThreadPoolExecutor(max_workers=20) as executor:
        futures = {executor.submit(_run, t): t for t in tasks}
        for future in as_completed(futures):
            key, data, err = future.result()
            results[key] = (data, err)
            if progress and task_id:
                progress.advance(task_id)
    
    return results
