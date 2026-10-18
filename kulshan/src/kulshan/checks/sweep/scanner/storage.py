"""Scan for orphaned storage resources: empty S3 buckets, stale ECR repos."""

from datetime import datetime, timezone
from typing import Dict, List, Tuple
from ..utils.aws import safe_api_call

from .evidence import qualify_findings


def scan_storage(
    session, regions, progress=None, task_id=None, *, include_global=True
) -> Tuple[List[Dict], List[str]]:
    """Find orphaned storage resources."""
    orphans = []
    errors = []

    # --- Empty S3 Buckets (global scan, done once) ---
    if include_global:
        try:
            s3 = session.client("s3", region_name="us-east-1")
            resp, err = safe_api_call(s3, "list_buckets")
        except Exception as exc:
            resp, err = None, f"s3.list_buckets (us-east-1): {exc}"
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
                    if not isinstance(obj_resp, dict) or not isinstance(
                        obj_resp.get("KeyCount"), int
                    ):
                        errors.append(f"s3.list_objects_v2 ({name}, us-east-1): malformed response")
                        continue
                    if (
                        obj_resp["KeyCount"] == 0
                        and not obj_resp.get("Contents")
                        and not obj_resp.get("IsTruncated")
                    ):
                        orphans.append(
                            {
                                "resource_id": name,
                                "resource_type": "S3 Bucket (no current objects)",
                                "category": "storage",
                                "region": "global",
                                "reason": (
                                    "No current objects; versions and "
                                    "recovery dependencies unverified"
                                ),
                                "age_days": age_days,
                                "monthly_cost": None,
                                "created": created.isoformat(),
                                "tags": _get_bucket_tags(s3, name, errors),
                                "cleanup_action": f"aws s3 rb s3://{name}",
                                "confidence": "medium",
                            }
                        )
                except Exception as exc:
                    errors.append(f"s3.list_objects_v2 ({name}, us-east-1): {exc}")

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
                images_resp, images_err = safe_api_call(
                    ecr, "list_images", repositoryName=repo_name
                )
                if images_err:
                    errors.append(f"ecr.list_images ({region}): {images_err}")
                    continue
                image_ids = (images_resp or {}).get("imageIds", [])
                if not image_ids:
                    created = repo.get("createdAt", datetime.now(timezone.utc))
                    age_days = (datetime.now(timezone.utc) - created).days
                    orphans.append(
                        {
                            "resource_id": repo_name,
                            "resource_type": "ECR Repository (empty)",
                            "category": "storage",
                            "region": region,
                            "reason": "No images in repository",
                            "age_days": age_days,
                            "monthly_cost": None,
                            "created": created.isoformat(),
                            "tags": {},
                            "cleanup_action": f"aws ecr delete-repository --repository-name {repo_name} --region {region}",
                            "confidence": "medium",
                        }
                    )
        except Exception as e:
            errors.append(f"ECR ({region}): {e}")

        if progress and task_id:
            progress.advance(task_id)

    return qualify_findings(orphans), errors


def _get_bucket_tags(s3, bucket_name, errors):
    try:
        resp = s3.get_bucket_tagging(Bucket=bucket_name)
        return {t["Key"]: t["Value"] for t in resp.get("TagSet", [])}
    except Exception as exc:
        errors.append(f"s3.get_bucket_tagging ({bucket_name}, us-east-1): {exc}")
        return None
