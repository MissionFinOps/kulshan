# DR (Disaster Recovery / Resilience)

**Check pack:** `Kulshan.checks.dr`
**Orchestrator key:** `dr`
**Score weight:** 12% (see `TOOL_WEIGHTS` in `kulshan/src/kulshan/orchestrator.py`)
**IAM policy:** [`kulshan/iam/per-check/dr.json`](../../kulshan/iam/per-check/dr.json)

## What it does

Scores disaster-recovery readiness 0-100 by auditing backups, multi-AZ deployments, cross-region replication, RTO/RPO gaps, and single points of failure. Simulates AZ and region failures with estimated recovery times.

## What it scans

| Category | Weight | What it checks |
|----------|--------|----------------|
| Backup Coverage | 25% | AWS Backup plans, vaults, recovery points, protected resources |
| Multi-AZ Deployment | 20% | EC2 AZ spread, ASG config, LB cross-AZ, RDS Multi-AZ |
| Data Durability | 20% | RDS backup retention, S3 versioning, DynamoDB PITR, snapshot freshness |
| Failover Readiness | 15% | Route 53 health checks, failover routing, ElastiCache auto-failover |
| Recovery Freshness | 10% | Age of most recent recovery points vs RPO targets |
| Cross-Region Posture | 10% | S3 cross-region replication, read replicas, global databases |

## Special features

- **Disaster simulation**: simulates AZ or region failure, estimates recovery time and data loss
- **SPOF detection**: identifies single points of failure with blast radius ("47 instances lose outbound internet")

## How to run

This pack runs as part of the unified Kulshan scan:

```bash
Kulshan Report                                   # all packs, all enabled regions
Kulshan Report --quick                           # 3 regions
Kulshan Report --format html -o report.html      # HTML output
```

A per-pack-only CLI (`Kulshan scan dr`) is not exposed today.

## Permissions

Read-only. Recommended: AWS managed `ViewOnlyAccess` + `AWSBackupServiceRolePolicyForBackup`. Granular per-pack policy at [`kulshan/iam/per-check/dr.json`](../../kulshan/iam/per-check/dr.json).

## Cost

$0.
