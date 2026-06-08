"""Scan IaC coverage: compare actual resources against CFN-managed resources."""

from typing import Dict, List, Tuple
from ..utils.aws import safe_api_call, paginate_all


def scan_coverage(session, regions, progress=None, task_id=None) -> Tuple[Dict, List[str]]:
    """Determine what % of resources are managed by CloudFormation."""
    findings = []
    errors = []
    coverage = {}

    for region in regions:
        cfn = session.client("cloudformation", region_name=region)
        ec2 = session.client("ec2", region_name=region)

        # Get all CFN-managed physical resource IDs
        cfn_managed = set()
        stacks, err = paginate_all(cfn, "list_stacks", "StackSummaries")
        if err:
            errors.append(f"CFN coverage ({region}): {err}")
        else:
            active = [s for s in stacks if s.get("StackStatus") not in
                      ("DELETE_COMPLETE", "DELETE_IN_PROGRESS")]
            for stack in active:
                resources, r_err = paginate_all(cfn, "list_stack_resources", "StackResourceSummaries",
                                                 StackName=stack["StackName"])
                if not r_err:
                    for r in resources:
                        pid = r.get("PhysicalResourceId", "")
                        if pid:
                            cfn_managed.add(pid)

        # Count actual resources vs managed
        # EC2 Instances
        inst_resp, _ = safe_api_call(ec2, "describe_instances",
                                      Filters=[{"Name": "instance-state-name", "Values": ["running", "stopped"]}])
        actual_ec2 = []
        for res in (inst_resp or {}).get("Reservations", []):
            for inst in res.get("Instances", []):
                actual_ec2.append(inst["InstanceId"])
        managed_ec2 = [i for i in actual_ec2 if i in cfn_managed]
        _add_coverage(coverage, "EC2 Instances", len(actual_ec2), len(managed_ec2), region)

        # Security Groups
        sg_resp, _ = safe_api_call(ec2, "describe_security_groups")
        actual_sg = [sg["GroupId"] for sg in (sg_resp or {}).get("SecurityGroups", [])
                     if sg.get("GroupName") != "default"]
        managed_sg = [s for s in actual_sg if s in cfn_managed]
        _add_coverage(coverage, "Security Groups", len(actual_sg), len(managed_sg), region)

        # S3 Buckets (global, only check once)
        if region == (regions[0] if regions else "us-east-1"):
            s3 = session.client("s3", region_name="us-east-1")
            buckets_resp, _ = safe_api_call(s3, "list_buckets")
            actual_s3 = [b["Name"] for b in (buckets_resp or {}).get("Buckets", [])]
            managed_s3 = [b for b in actual_s3 if b in cfn_managed]
            _add_coverage(coverage, "S3 Buckets", len(actual_s3), len(managed_s3), "global")

        # Lambda Functions
        try:
            lam = session.client("lambda", region_name=region)
            fns, _ = paginate_all(lam, "list_functions", "Functions")
            actual_lam = [f["FunctionName"] for f in fns]
            managed_lam = [f for f in actual_lam if f in cfn_managed]
            _add_coverage(coverage, "Lambda Functions", len(actual_lam), len(managed_lam), region)
        except Exception:
            pass

        # RDS Instances
        try:
            rds = session.client("rds", region_name=region)
            dbs, _ = paginate_all(rds, "describe_db_instances", "DBInstances")
            actual_rds = [d["DBInstanceIdentifier"] for d in dbs]
            managed_rds = [d for d in actual_rds if d in cfn_managed]
            _add_coverage(coverage, "RDS Instances", len(actual_rds), len(managed_rds), region)
        except Exception:
            pass

        if progress and task_id:
            progress.advance(task_id)

    # Aggregate coverage across regions
    aggregated = {}
    for rtype, entries in coverage.items():
        total = sum(e["total"] for e in entries)
        managed = sum(e["managed"] for e in entries)
        pct = round(managed / total * 100, 1) if total > 0 else 0
        aggregated[rtype] = {"total": total, "managed": managed, "unmanaged": total - managed, "coverage_pct": pct}

    # Overall coverage
    grand_total = sum(a["total"] for a in aggregated.values())
    grand_managed = sum(a["managed"] for a in aggregated.values())
    overall_pct = round(grand_managed / grand_total * 100, 1) if grand_total > 0 else 0

    # Findings
    if overall_pct < 50 and grand_total > 10:
        findings.append({
            "category": "coverage",
            "severity": "high",
            "title": f"Only {overall_pct:.0f}% of resources are managed by CloudFormation",
            "detail": f"{grand_managed}/{grand_total} resources are in CFN stacks. {grand_total - grand_managed} are unmanaged.",
            "recommendation": "Import unmanaged resources into CloudFormation stacks or document exceptions.",
        })
    elif overall_pct < 80 and grand_total > 10:
        findings.append({
            "category": "coverage",
            "severity": "medium",
            "title": f"{overall_pct:.0f}% IaC coverage, {grand_total - grand_managed} unmanaged resources",
            "detail": f"{grand_managed}/{grand_total} resources are in CFN stacks.",
            "recommendation": "Increase IaC coverage for better governance and reproducibility.",
        })

    stats = {
        "coverage": aggregated,
        "overall_total": grand_total,
        "overall_managed": grand_managed,
        "overall_pct": overall_pct,
    }

    return {"stats": stats, "findings": findings}, errors


def _add_coverage(coverage, rtype, total, managed, region):
    if rtype not in coverage:
        coverage[rtype] = []
    coverage[rtype].append({"region": region, "total": total, "managed": managed})
