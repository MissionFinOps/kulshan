# Tag (FinOps / Tag Governance)

**Check pack:** `Kulshan.checks.tag`
**Orchestrator key:** `tag`
**Score weight:** 8% (see `TOOL_WEIGHTS` in `kulshan/src/kulshan/orchestrator.py`)
**IAM policy:** [`kulshan/iam/per-check/tag.json`](../../kulshan/iam/per-check/tag.json)

## What it does

Audits every resource against a tagging policy, scores compliance 0-100, surfaces the "dark money" (spend that can't be attributed to any team), detects tag-value chaos, and generates fix scripts.

## Key concepts

- **Dark Money**: spend that can't be attributed to any team because resources lack required tags
- **Tag Value Chaos**: multiple variations of the same value (e.g. "production", "Production", "prod", "PROD")
- **Tag Compliance**: % of resources with all required tags present and valid

## How to run

This pack runs as part of the unified Kulshan scan:

```bash
Kulshan Report                                   # all packs, all enabled regions
Kulshan Report --quick                           # 3 regions
Kulshan Report --format html -o report.html      # HTML output
```

A per-pack-only CLI (`Kulshan scan tag`) is not exposed today.

## Permissions

Read-only. Key actions: `tag:GetResources`, `tag:GetTagKeys`, `tag:GetTagValues`, plus `ce:GetCostAndUsage` for dark-money analysis. Granular per-pack policy at [`kulshan/iam/per-check/tag.json`](../../kulshan/iam/per-check/tag.json).

## Cost

$0 (unless using Cost Explorer for dark-money analysis: same $0.01/request as the cost pack).
