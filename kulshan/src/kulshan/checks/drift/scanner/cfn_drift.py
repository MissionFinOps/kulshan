"""Scan CloudFormation stacks for drift, parallel detection."""

import time
import fnmatch
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Dict, List, Tuple
from ..utils.aws import safe_api_call, paginate_all

SECURITY_PROPERTIES = {
    "SecurityGroupIngress", "SecurityGroupEgress", "IpPermissions", "IpPermissionsEgress",
    "PolicyDocument", "Policy", "BucketPolicy", "AccessControl", "PublicAccessBlockConfiguration",
    "InstanceType", "SubnetId", "VpcId", "Encrypted", "KmsKeyId", "MultiAZ",
    "BackupRetentionPeriod", "DeletionProtection", "PubliclyAccessible",
}


def scan_cfn_drift(session, regions, stack_filter=None, timeout=120,
                    progress=None, task_id=None) -> Tuple[Dict, List[str]]:
    """Detect drift across all CloudFormation stacks using parallel detection."""
    findings = []
    errors = []
    stats = {
        "total_stacks": 0, "stacks_checked": 0, "stacks_drifted": 0,
        "stacks_in_sync": 0, "stacks_failed": 0, "stacks_timeout": 0,
        "drifted_resources": [],
        "drift_by_severity": {"critical": 0, "moderate": 0, "cosmetic": 0},
        "stacks": [],
    }

    for region in regions:
        cfn = session.client("cloudformation", region_name=region)

        stacks, err = paginate_all(cfn, "list_stacks", "StackSummaries")
        if err:
            errors.append(f"CFN ({region}): {err}")
            if progress and task_id:
                progress.advance(task_id)
            continue

        active_stacks = [s for s in stacks
                         if s.get("StackStatus") in ("CREATE_COMPLETE", "UPDATE_COMPLETE",
                                                      "UPDATE_ROLLBACK_COMPLETE", "IMPORT_COMPLETE")]
        if stack_filter:
            active_stacks = [s for s in active_stacks
                             if fnmatch.fnmatch(s.get("StackName", ""), stack_filter)]

        stats["total_stacks"] += len(active_stacks)

        # Phase 1: Trigger all drift detections in parallel
        pending = {}  # detection_id -> stack_name
        with ThreadPoolExecutor(max_workers=5) as executor:
            futures = {}
            for stack in active_stacks:
                f = executor.submit(_trigger_detection, cfn, stack["StackName"])
                futures[f] = stack["StackName"]

            for future in as_completed(futures):
                stack_name = futures[future]
                detection_id, det_err = future.result()
                if det_err:
                    stats["stacks_failed"] += 1
                    errors.append(f"Drift detect ({region}/{stack_name}): {det_err}")
                elif detection_id:
                    pending[detection_id] = stack_name
                else:
                    stats["stacks_failed"] += 1

        # Phase 2: Poll all detections until complete or timeout
        completed = {}  # stack_name -> drift_status_resp
        deadline = time.time() + timeout
        while pending and time.time() < deadline:
            done_ids = []
            for det_id, stack_name in pending.items():
                resp, err = safe_api_call(cfn, "describe_stack_drift_detection_status",
                                           StackDriftDetectionId=det_id)
                if err:
                    done_ids.append(det_id)
                    stats["stacks_failed"] += 1
                    continue
                status = (resp or {}).get("DetectionStatus", "")
                if status == "DETECTION_COMPLETE":
                    completed[stack_name] = resp
                    done_ids.append(det_id)
                elif status == "DETECTION_FAILED":
                    done_ids.append(det_id)
                    stats["stacks_failed"] += 1
            for did in done_ids:
                pending.pop(did, None)
            if pending:
                time.sleep(2)

        # Mark remaining as timeout
        for det_id, stack_name in pending.items():
            stats["stacks_timeout"] += 1
            errors.append(f"Drift detection timeout ({region}/{stack_name})")

        # Phase 3: Describe drifted resources in parallel
        drifted_stacks = {name: resp for name, resp in completed.items()
                          if resp.get("StackDriftStatus") == "DRIFTED"}
        in_sync_count = len(completed) - len(drifted_stacks)
        stats["stacks_checked"] += len(completed)
        stats["stacks_in_sync"] += in_sync_count
        stats["stacks_drifted"] += len(drifted_stacks)

        with ThreadPoolExecutor(max_workers=5) as executor:
            futures = {}
            for stack_name in drifted_stacks:
                f = executor.submit(_describe_drifts, cfn, stack_name, region)
                futures[f] = stack_name

            for future in as_completed(futures):
                stack_name = futures[future]
                stack_info, resource_drifts = future.result()
                for rd in resource_drifts:
                    stats["drift_by_severity"][rd["severity"]] += 1
                stats["drifted_resources"].extend(resource_drifts)
                stats["stacks"].append(stack_info)

        # Add in-sync stacks
        for name, resp in completed.items():
            if resp.get("StackDriftStatus") != "DRIFTED":
                stats["stacks"].append({"name": name, "region": region,
                                         "drift_status": "IN_SYNC", "drifted_resources": []})

        if progress and task_id:
            progress.advance(task_id)

    # Generate findings
    if stats["stacks_drifted"] > 0:
        pct = stats["stacks_drifted"] / max(stats["stacks_checked"], 1) * 100
        findings.append({"category": "drift",
                         "severity": "high" if pct > 30 else "medium",
                         "title": f"{stats['stacks_drifted']}/{stats['stacks_checked']} stacks have drifted ({pct:.0f}%)",
                         "detail": f"{len(stats['drifted_resources'])} total drifted resources.",
                         "recommendation": "Review drifted stacks and update templates or revert changes."})

    crit = stats["drift_by_severity"]["critical"]
    if crit > 0:
        findings.append({"category": "drift", "severity": "critical",
                         "title": f"{crit} security-relevant drift(s) detected",
                         "detail": "Security groups, policies, or encryption settings modified outside IaC.",
                         "recommendation": "Immediately review and revert security-relevant drift."})

    if stats["stacks_timeout"] > 0:
        findings.append({"category": "drift", "severity": "low",
                         "title": f"{stats['stacks_timeout']} stack(s) timed out during drift detection",
                         "detail": "Detection didn't complete within the timeout window.",
                         "recommendation": "Re-run with --timeout flag or target specific stacks with --stacks."})

    return {"stats": stats, "findings": findings}, errors


def _trigger_detection(cfn, stack_name):
    """Trigger drift detection for a single stack."""
    resp, err = safe_api_call(cfn, "detect_stack_drift", StackName=stack_name)
    if err:
        return None, err
    return (resp or {}).get("StackDriftDetectionId"), None


def _describe_drifts(cfn, stack_name, region):
    """Describe resource-level drifts for a drifted stack."""
    stack_info = {"name": stack_name, "region": region, "drift_status": "DRIFTED", "drifted_resources": []}
    resource_drifts = []

    resp, err = safe_api_call(cfn, "describe_stack_resource_drifts",
                               StackName=stack_name,
                               StackResourceDriftStatusFilters=["MODIFIED", "DELETED"])
    if err or not resp:
        return stack_info, resource_drifts

    for drift in resp.get("StackResourceDrifts", []):
        property_diffs = drift.get("PropertyDifferences", [])
        severity = _classify_severity(property_diffs)
        diff_summary = [{"path": pd.get("PropertyPath", "?"),
                         "expected": str(pd.get("ExpectedValue", ""))[:80],
                         "actual": str(pd.get("ActualValue", ""))[:80],
                         "type": pd.get("DifferenceType", "?")}
                        for pd in property_diffs[:5]]

        rd = {"stack": stack_name, "region": region,
              "resource_type": drift.get("ResourceType", "?"),
              "logical_id": drift.get("LogicalResourceId", "?"),
              "physical_id": drift.get("PhysicalResourceId", "?"),
              "drift_type": drift.get("StackResourceDriftStatus", "?"),
              "severity": severity, "property_diffs": diff_summary}
        resource_drifts.append(rd)
        stack_info["drifted_resources"].append(rd)

    return stack_info, resource_drifts


def _classify_severity(property_diffs):
    for pd in property_diffs:
        path = pd.get("PropertyPath", "")
        prop_name = path.split("/")[-1] if "/" in path else path
        if prop_name in SECURITY_PROPERTIES:
            return "critical"
        if any(sec in path for sec in ("Security", "Policy", "Encrypt", "Public", "Access")):
            return "critical"
    for pd in property_diffs:
        path = pd.get("PropertyPath", "")
        if any(k in path for k in ("InstanceType", "SubnetId", "VpcId", "Engine")):
            return "moderate"
    return "cosmetic"
