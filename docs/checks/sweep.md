# Sweep (Waste Detection)

**Check pack:** `Kulshan.checks.sweep`
**Orchestrator key:** `sweep`
**Score weight:** 10% (see `TOOL_WEIGHTS` in `kulshan/src/kulshan/orchestrator.py`)
**IAM policy:** [`kulshan/iam/per-check/sweep.json`](../../kulshan/iam/per-check/sweep.json)

## What it does

Finds every forgotten, orphaned, and zombie resource in the AWS account and calculates exact monthly waste. Scores account hygiene 0-100, visualizes the "Resource Graveyard," and generates cleanup scripts.

## What it scans

| Category | Resources | Examples |
|----------|-----------|----------|
| Compute | EBS volumes, EIPs, snapshots, AMIs, ENIs | Unattached volumes, unused Elastic IPs, orphaned snapshots |
| Network | Security groups, NAT gateways, load balancers | Unused SGs, idle NAT GWs (zero traffic), LBs with no healthy targets |
| Storage | S3 buckets, ECR repositories | Empty buckets, ECR repos with no images |
| Database | RDS snapshots, RDS instances | Manual snapshots 90+ days old, stopped instances (still billed) |
| Monitoring | Log groups, CloudWatch alarms, Lambda functions | Empty log groups, stale alarms, functions not invoked in 90+ days |

## Scoring breakdown (0-100): account hygiene

| Category | Weight | What it measures |
|----------|--------|------------------|
| Compute Hygiene | 25% | Unattached EBS, unused EIPs, orphaned snapshots, stale AMIs |
| Network Hygiene | 20% | Unused SGs, idle NAT GWs, idle load balancers |
| Storage Hygiene | 20% | Empty buckets, empty ECR repos |
| Database Hygiene | 15% | Old manual snapshots, stopped RDS instances |
| Monitoring Hygiene | 10% | Empty log groups, stale alarms, unused Lambda functions |
| Age Factor | 10% | How long orphans have existed (older = worse) |

## Confidence levels

Each orphan is tagged:
- **High**: safe to delete (unattached EBS, unused EIP, idle NAT GW)
- **Medium**: likely orphaned, review recommended (orphaned snapshots, unused SGs)
- **Low**: might be intentional, needs human judgment (unused AMIs, stopped RDS)

## How to run

This pack runs as part of the unified Kulshan scan:

```bash
Kulshan Report                                   # all packs, all enabled regions
Kulshan Report --quick                           # 3 regions
Kulshan Report --format html -o report.html      # HTML output
```

A per-pack-only CLI (`Kulshan scan sweep`) is not exposed today.

## Permissions

Read-only. Recommended: AWS managed `ViewOnlyAccess`. Granular per-pack policy at [`kulshan/iam/per-check/sweep.json`](../../kulshan/iam/per-check/sweep.json).

## Cost

$0. All API calls are free tier.
