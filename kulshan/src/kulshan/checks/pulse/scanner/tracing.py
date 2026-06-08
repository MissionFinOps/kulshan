"""Scan tracing and advanced observability: X-Ray, Container Insights, Config."""

from typing import Dict, List, Tuple
from ..utils.aws import safe_api_call, paginate_all


def scan_tracing(session, regions, progress=None, task_id=None) -> Tuple[Dict, List[str]]:
    """Audit tracing and advanced observability features."""
    findings = []
    errors = []
    stats = {
        "xray_groups": 0,
        "config_recorders": 0,
        "config_enabled_regions": 0,
        "ecs_clusters": {"total": 0, "with_insights": 0},
        "eks_clusters": {"total": 0, "with_logging": 0},
        "lambda_tracing": {"total": 0, "with_xray": 0},
    }

    for region in regions:
        # --- AWS Config ---
        try:
            config = session.client("config", region_name=region)
            rec_resp, err = safe_api_call(config, "describe_configuration_recorders")
            if not err:
                recorders = (rec_resp or {}).get("ConfigurationRecorders", [])
                stats["config_recorders"] += len(recorders)
                if recorders:
                    stats["config_enabled_regions"] += 1
        except Exception as e:
            errors.append(f"Config ({region}): {e}")

        # --- ECS Container Insights ---
        try:
            ecs = session.client("ecs", region_name=region)
            clusters, err = paginate_all(ecs, "list_clusters", "clusterArns")
            if not err and clusters:
                desc_resp, _ = safe_api_call(ecs, "describe_clusters", clusters=clusters[:10],
                                              include=["SETTINGS"])
                for cluster in (desc_resp or {}).get("clusters", []):
                    stats["ecs_clusters"]["total"] += 1
                    settings = cluster.get("settings", [])
                    for s in settings:
                        if s.get("name") == "containerInsights" and s.get("value") == "enabled":
                            stats["ecs_clusters"]["with_insights"] += 1
        except Exception as e:
            errors.append(f"ECS ({region}): {e}")

        # --- EKS Control Plane Logging ---
        try:
            eks = session.client("eks", region_name=region)
            eks_clusters, err = paginate_all(eks, "list_clusters", "clusters")
            if not err:
                for cluster_name in eks_clusters:
                    desc_resp, _ = safe_api_call(eks, "describe_cluster", name=cluster_name)
                    if desc_resp:
                        cluster = desc_resp.get("cluster", {})
                        stats["eks_clusters"]["total"] += 1
                        logging_config = cluster.get("logging", {}).get("clusterLogging", [])
                        for lc in logging_config:
                            if lc.get("enabled"):
                                stats["eks_clusters"]["with_logging"] += 1
                                break
        except Exception as e:
            errors.append(f"EKS ({region}): {e}")

        # --- Lambda X-Ray Tracing ---
        try:
            lam = session.client("lambda", region_name=region)
            fns, err = paginate_all(lam, "list_functions", "Functions")
            if not err:
                for fn in fns:
                    stats["lambda_tracing"]["total"] += 1
                    tracing = fn.get("TracingConfig", {}).get("Mode", "PassThrough")
                    if tracing == "Active":
                        stats["lambda_tracing"]["with_xray"] += 1
        except Exception as e:
            errors.append(f"Lambda tracing ({region}): {e}")

        # --- X-Ray Groups ---
        try:
            xray = session.client("xray", region_name=region)
            groups_resp, err = safe_api_call(xray, "get_groups")
            if not err:
                stats["xray_groups"] += len((groups_resp or {}).get("Groups", []))
        except Exception as e:
            errors.append(f"X-Ray ({region}): {e}")

        if progress and task_id:
            progress.advance(task_id)

    # Findings
    if stats["config_enabled_regions"] == 0:
        findings.append({
            "category": "tracing",
            "severity": "high",
            "title": "AWS Config is not enabled in any region",
            "detail": "Configuration changes are not being tracked. Drift and compliance violations are invisible.",
            "recommendation": "Enable AWS Config with a recorder in all active regions.",
        })

    ecs_total = stats["ecs_clusters"]["total"]
    ecs_insights = stats["ecs_clusters"]["with_insights"]
    if ecs_total > 0 and ecs_insights < ecs_total:
        findings.append({
            "category": "tracing",
            "severity": "medium",
            "title": f"{ecs_total - ecs_insights}/{ecs_total} ECS clusters lack Container Insights",
            "detail": "Container-level metrics (CPU, memory, network) are not collected.",
            "recommendation": "Enable Container Insights on all ECS clusters.",
        })

    eks_total = stats["eks_clusters"]["total"]
    eks_logging = stats["eks_clusters"]["with_logging"]
    if eks_total > 0 and eks_logging < eks_total:
        findings.append({
            "category": "tracing",
            "severity": "medium",
            "title": f"{eks_total - eks_logging}/{eks_total} EKS clusters lack control plane logging",
            "detail": "API server, audit, and authenticator logs are not being captured.",
            "recommendation": "Enable control plane logging for all EKS clusters.",
        })

    lam_total = stats["lambda_tracing"]["total"]
    lam_xray = stats["lambda_tracing"]["with_xray"]
    if lam_total > 0 and lam_xray == 0:
        findings.append({
            "category": "tracing",
            "severity": "medium",
            "title": f"No Lambda functions have X-Ray tracing enabled (0/{lam_total})",
            "detail": "Distributed tracing is not available for serverless workloads.",
            "recommendation": "Enable active X-Ray tracing on Lambda functions.",
        })

    return {"stats": stats, "findings": findings}, errors
