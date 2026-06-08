# Security (Posture)

**Check pack:** `Kulshan.checks.security`
**Orchestrator key:** `security`
**Score weight:** 15% (see `TOOL_WEIGHTS` in `kulshan/src/kulshan/orchestrator.py`)
**IAM policy:** [`kulshan/iam/per-check/security.json`](../../kulshan/iam/per-check/security.json)

## What it does

Scans the AWS account for security misconfigurations, maps attack paths, scores posture 0-100, and generates prioritized findings with compliance mapping (CIS, NIST 800-53, SOC 2), breach-cost estimates, and remediation code.

## 50 security checks

| Category | Checks | Examples |
|----------|--------|----------|
| Identity & Access | 11 | Root MFA, stale keys, admin policies, privilege escalation, cross-account trusts |
| Network Exposure | 6 | Open security groups, SSH/RDP/DB ports exposed, missing flow logs |
| Data Protection | 9 | Public S3 buckets, unencrypted RDS/EBS, public snapshots |
| Compute Security | 6 | IMDSv1, public EC2, Lambda secrets, outdated runtimes |
| Logging & Monitoring | 9 | CloudTrail, GuardDuty, Config, Access Analyzer |
| Encryption & Secrets | 3 | KMS rotation, Secrets Manager, expiring certificates |

## Scoring (0-100)

Weighted by category with severity multipliers for critical findings.

## Special features

- **Attack-path discovery**: builds a resource relationship graph and finds paths from internet to sensitive resources
- **Crown Jewels mode**: inside-out analysis of the most critical resources
- **Breach-cost estimation**: based on IBM benchmarks
- **Blame mode**: CloudTrail attribution (who created each risk)
- **Remediation code**: Terraform or boto3 fix scripts
- **Scan comparison**: diff against previous scan results

## How to run

This pack runs as part of the unified Kulshan scan:

```bash
Kulshan Report                                   # all packs, all enabled regions
Kulshan Report --quick                           # 3 regions
Kulshan Report --format html -o report.html      # HTML output
```

A per-pack-only CLI (`Kulshan scan security`) is not exposed today.

## Permissions

Recommended: AWS managed `SecurityAudit` + `ViewOnlyAccess`. Granular per-pack policy at [`kulshan/iam/per-check/security.json`](../../kulshan/iam/per-check/security.json).

## Cost

$0. All API calls are free tier.
