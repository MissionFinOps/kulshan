"""Scan for orphaned storage resources: empty S3 buckets, stale ECR repos."""

from datetime import datetime, timezone
from typing import Dict, List, Tuple
from ..utils.aws import safe_api_call


def scan_storage(session, regions, progress=None, task_id=None) -> Tuple[List[Dict], List[str]]:
    """Find orphaned storage resources."""
    orphans = []
    errors = []

    # --- Empty S3 Buckets (global scan, done once) ---
    s3 = session.client("s3", region_name="us-east-1")
    resp, err = safe_api_call(s3, "list_buckets")
    if err:
        errors.append(f"S3: {err}")
    else:
        for bucket in (resp or {}).get("Buckets", []):
            name = bucket["Name"]
            created = bucket.get("CreationDate", datetime.now(timezone.utc))
            age_days = (datetime.now(timezone.utc) - created).days

            # Check if bucket is empty
            try:
                obj_resp = s3.list_objects_v2(Bucket=name, MaxKeys=1)
                if obj_resp.get("KeyCount", 0) == 0:
                    orphans.append({
                        "resource_id": name,
                        "resource_type": "S3 Bucket (empty)",
                        "category": "storage",
                        "region": "global",
                        "reason": f"Empty bucket, created {age_days} days ago",
                        "age_days": age_days,
                        "monthly_cost": 0,
                        "created": created.isoformat(),
                        "tags": _get_bucket_tags(s3, name),
                        "cleanup_action": f"aws s3 rb s3://{name}",
                        "confidence": "medium",
                    })
            except Exception:
                pass  # Access denied or other issue, skip

    # --- Empty ECR Repositories ---
    for region in regions:
        try:
            ecr = session.client("ecr", region_name=region)
            repos_resp, err = safe_api_call(ecr, "describe_repositories")
            if err:
                errors.append(f"ECR ({region}): {err}")
                continue

            for repo in (repos_resp or {}).get("repositories", []):
                repo_name = repo["repositoryName"]
                images_resp, _ = safe_api_call(ecr, "list_images", repositoryName=repo_name)
                image_ids = (images_resp or {}).get("imageIds", [])
                if not image_ids:
                    created = repo.get("createdAt", datetime.now(timezone.utc))
                    age_days = (datetime.now(timezone.utc) - created).days
                    orphans.append({
                        "resource_id": repo_name,
                        "resource_type": "ECR Repository (empty)",
                        "category": "storage",
                        "region": region,
                        "reason": "No images in repository",
                        "age_days": age_days,
                        "monthly_cost": 0,
                        "created": created.isoformat(),
                        "tags": {},
                        "cleanup_action": f"aws ecr delete-repository --repository-name {repo_name} --region {region}",
                        "confidence": "medium",
                    })
        except Exception as e:
            errors.append(f"ECR ({region}): {e}")

        if progress and task_id:
            progress.advance(task_id)

    return orphans, errors


def _get_bucket_tags(s3, bucket_name):
    try:
        resp = s3.get_bucket_tagging(Bucket=bucket_name)
        return {t["Key"]: t["Value"] for t in resp.get("TagSet", [])}
    except Exception:
        return {}
