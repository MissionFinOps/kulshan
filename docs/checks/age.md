# Age (Lifecycle / Freshness)

**Check pack:** `Kulshan.checks.age`
**Orchestrator key:** `age`
**Score weight:** 8% (see `TOOL_WEIGHTS` in `kulshan/src/kulshan/orchestrator.py`)
**IAM policy:** [`kulshan/iam/per-check/age.json`](../../kulshan/iam/per-check/age.json)

## What it does

Finds every resource approaching end-of-life, end-of-support, or staleness. Calculates the "staleness tax": the dollar cost of running outdated infrastructure. Scores freshness 0-100.

## What it checks

| Category | Weight | Resources |
|----------|--------|-----------|
| Runtime Freshness | 25% | Lambda runtimes, EKS versions, ElastiCache Redis versions |
| Engine Freshness | 25% | RDS/Aurora engine versions vs end-of-support dates |
| Instance Freshness | 20% | EC2 uptime age (180+ days flagged, 365+ critical) |
| Certificate Health | 15% | ACM certificate expiration, auto-renewal status |
| Storage Modernization | 15% | EBS gp2 → gp3 migration opportunities |

## Embedded EOL database

Includes EOL/EOS dates for:
- Lambda runtimes (Python, Node.js, Java, .NET, Ruby, Go)
- RDS engines (MySQL, PostgreSQL, MariaDB, Oracle, SQL Server)
- Aurora engine versions
- EKS Kubernetes versions
- ElastiCache Redis versions

## How to run

This pack runs as part of the unified Kulshan scan:

```bash
Kulshan Report                                   # all packs, all enabled regions
Kulshan Report --quick                           # 3 regions
Kulshan Report --format html -o report.html      # HTML output
```

A per-pack-only CLI (`Kulshan scan age`) is not exposed today.

## Permissions

Read-only. Key actions: `lambda:List*`, `rds:Describe*`, `ec2:Describe*`, `eks:List*`, `acm:List*`. Granular per-pack policy at [`kulshan/iam/per-check/age.json`](../../kulshan/iam/per-check/age.json).

## Cost

$0.
