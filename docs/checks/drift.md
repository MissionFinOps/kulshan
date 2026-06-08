# Drift (IaC Governance)

**Check pack:** `Kulshan.checks.drift`
**Orchestrator key:** `drift`
**Score weight:** 10% (see `TOOL_WEIGHTS` in `kulshan/src/kulshan/orchestrator.py`)
**IAM policy:** [`kulshan/iam/per-check/drift.json`](../../kulshan/iam/per-check/drift.json)

## What it does

Detects every resource that has drifted from its CloudFormation definition, classifies drift by severity (security-relevant vs cosmetic), and measures IaC coverage across the account.

## Scoring breakdown (0-100): drift health

| Category | Weight | What it measures |
|----------|--------|------------------|
| Stack Drift | 30% | % of CFN stacks with detected drift |
| Drift Severity | 25% | Security-relevant vs cosmetic drift |
| Unmanaged Resources | 20% | Resources not in any CFN stack |
| Drift Volume | 15% | Total number of drifted resources |
| IaC Coverage | 10% | % of resources managed by CloudFormation |

## Drift severity classification

- **Critical**: security groups, policies, encryption, public access settings changed
- **Moderate**: instance types, subnets, VPCs, engine versions changed
- **Cosmetic**: tags, descriptions, non-functional properties changed

## How to run

This pack runs as part of the unified Kulshan scan:

```bash
Kulshan Report                                   # all packs, all enabled regions
Kulshan Report --quick                           # 3 regions, skips coverage
Kulshan Report --format html -o report.html      # HTML output
```

A per-pack-only CLI (`Kulshan scan drift`) is not exposed today.

## Permissions

Read-only. Needs `cloudformation:Describe*`, `cloudformation:DetectStackDrift`, `cloudformation:DetectStackResourceDrift`. Granular per-pack policy at [`kulshan/iam/per-check/drift.json`](../../kulshan/iam/per-check/drift.json).

## Cost

$0.
