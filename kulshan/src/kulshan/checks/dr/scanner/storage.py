"""Scan storage resilience: S3 versioning, replication, lifecycle."""

from typing import Dict, List, Tuple
from ..utils.aws import safe_api_call


def scan_storage(session, regions, progress=None, task_id=None) -> Tuple[Dict, List[str]]:
    """Audit S3 storage resilience."""
    findings = []
    errors = []
    stats = {
        "buckets": [],
        "no_versioning": [],
        "no_replication": [],
        "no_lifecycle": [],
        "cross_region_replication": 0,
    }

    s3 = session.client("s3", region_name="us-east-1")
    resp, err = safe_api_call(s3, "list_buckets")
    if err:
        errors.append(f"S3: {err}")
        return {"stats": stats, "findings": findings}, errors

    buckets = (resp or {}).get("Buckets", [])

    for bucket in buckets:
        name = bucket["Name"]
        info = {"name": name, "versioning": False, "replication": False, "lifecycle": False}

        # Versioning
        ver_resp, ver_err = safe_api_call(s3, "get_bucket_versioning", Bucket=name)
        if not ver_err and ver_resp:
            status = ver_resp.get("Status", "")
            info["versioning"] = status == "Enabled"
        if not info["versioning"]:
            stats["no_versioning"].append(name)

        # Replication
        rep_resp, rep_err = safe_api_call(s3, "get_bucket_replication", Bucket=name)
        if not rep_err and rep_resp:
            rules = rep_resp.get("ReplicationConfiguration", {}).get("Rules", [])
            if rules:
                info["replication"] = True
                stats["cross_region_replication"] += 1
        if not info["replication"]:
            stats["no_replication"].append(name)

        # Lifecycle
        lc_resp, lc_err = safe_api_call(s3, "get_bucket_lifecycle_configuration", Bucket=name)
        if not lc_err and lc_resp:
            rules = lc_resp.get("Rules", [])
            if rules:
                info["lifecycle"] = True
        if not info["lifecycle"]:
            stats["no_lifecycle"].append(name)

        stats["buckets"].append(info)

    # Generate findings
    total = len(buckets)
    if total > 0:
        no_ver_count = len(stats["no_versioning"])
        if no_ver_count > 0:
            pct = no_ver_count / total * 100
            findings.append({
                "category": "storage",
                "severity": "high" if pct > 50 else "medium",
                "title": f"{no_ver_count}/{total} S3 buckets have no versioning ({pct:.0f}%)",
                "detail": "Without versioning, accidental deletes or overwrites are permanent.",
                "recommendation": "Enable versioning on all buckets containing important data.",
            })

        if stats["cross_region_replication"] == 0:
            findings.append({
                "category": "storage",
                "severity": "medium",
                "title": "No S3 cross-region replication configured",
                "detail": "All bucket data exists in a single region. A regional outage could cause data unavailability.",
                "recommendation": "Enable cross-region replication for critical buckets.",
            })

    if progress and task_id:
        progress.advance(task_id)

    return {"stats": stats, "findings": findings}, errors
