"""Resource discovery via Resource Groups Tagging API + service-specific fallbacks."""

from typing import Dict, List, Tuple
from ..utils.aws import safe_api_call, paginate_all


def scan_all_resources(session, regions, progress=None, task_id=None):
    """Discover all resources and their tags across all regions."""
    all_resources = []
    errors = []

    # Phase 1: Resource Groups Tagging API (covers most resource types)
    for region in regions:
        client = session.client("resourcegroupstaggingapi", region_name=region)
        resources, err = paginate_all(client, "get_resources", "ResourceTagMappingList",
                                       ResourcesPerPage=100)
        if err:
            errors.append(f"Tagging API ({region}): {err}")
        for r in resources:
            arn = r.get("ResourceARN", "")
            tags = {t["Key"]: t["Value"] for t in r.get("Tags", [])}
            rtype = _extract_resource_type(arn)
            all_resources.append({
                "arn": arn,
                "resource_type": rtype,
                "service": _extract_service(arn),
                "region": region,
                "tags": tags,
                "tag_count": len(tags),
                "source": "tagging_api",
            })
        if progress and task_id:
            progress.advance(task_id)

    # Phase 2: S3 buckets (global, tagging API sometimes misses them)
    s3 = session.client("s3", region_name="us-east-1")
    buckets_resp, err = safe_api_call(s3, "list_buckets")
    if not err:
        existing_arns = {r["arn"] for r in all_resources}
        for bucket in (buckets_resp or {}).get("Buckets", []):
            name = bucket["Name"]
            arn = f"arn:aws:s3:::{name}"
            if arn not in existing_arns:
                tags = {}
                tag_resp, _ = safe_api_call(s3, "get_bucket_tagging", Bucket=name)
                if tag_resp:
                    tags = {t["Key"]: t["Value"] for t in tag_resp.get("TagSet", [])}
                all_resources.append({
                    "arn": arn, "resource_type": "s3:bucket", "service": "s3",
                    "region": "global", "tags": tags, "tag_count": len(tags), "source": "s3_api",
                })
    if progress and task_id:
        progress.advance(task_id)

    return all_resources, errors


def get_all_tag_keys(session, regions):
    """Get all tag keys in use across the account."""
    all_keys = set()
    for region in regions[:3]:  # Sample a few regions
        client = session.client("resourcegroupstaggingapi", region_name=region)
        resp, _ = safe_api_call(client, "get_tag_keys")
        if resp:
            all_keys.update(resp.get("TagKeys", []))
    return sorted(all_keys)


def get_tag_values(session, region, key):
    """Get all values for a specific tag key."""
    client = session.client("resourcegroupstaggingapi", region_name=region)
    resp, _ = safe_api_call(client, "get_tag_values", Key=key)
    if resp:
        return resp.get("TagValues", [])
    return []


def _extract_service(arn):
    parts = arn.split(":")
    return parts[2] if len(parts) > 2 else "unknown"


def _extract_resource_type(arn):
    parts = arn.split(":")
    if len(parts) >= 6:
        service = parts[2]
        resource = parts[5] if len(parts) > 5 else ""
        if "/" in resource:
            return f"{service}:{resource.split('/')[0]}"
        return f"{service}:{resource.split(':')[0] if ':' in resource else resource}"
    return "unknown"
