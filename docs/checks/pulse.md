# Pulse (Observability / Monitoring)

**Check pack:** `Kulshan.checks.pulse`
**Orchestrator key:** `pulse`
**Score weight:** 8% (see `TOOL_WEIGHTS` in `kulshan/src/kulshan/orchestrator.py`)
**IAM policy:** [`kulshan/iam/per-check/pulse.json`](../../kulshan/iam/per-check/pulse.json)

## What it does

Audits monitoring coverage, alarm effectiveness, and observability gaps. Scores observability maturity 0-100 and generates a Blind-Spot Heatmap showing which resources can fail silently.

## What it scans

| Category | Weight | What it checks |
|----------|--------|----------------|
| Log Coverage | 25% | CloudTrail, VPC Flow Logs, S3 access logging, log group retention |
| Alarm Coverage | 25% | CloudWatch alarms vs critical resources (blind-spot detection) |
| Metric Coverage | 20% | Resource-level monitoring gaps |
| Tracing & Config | 15% | X-Ray, AWS Config, ECS Container Insights, EKS control plane logging |
| Centralization | 15% | SNS topics, RDS enhanced monitoring, log aggregation |

## Key feature: Blind-Spot Heatmap

Shows resource types with their monitoring coverage percentage: making it immediately obvious which resources can break without anyone knowing.

## How to run

This pack runs as part of the unified Kulshan scan:

```bash
Kulshan Report                                   # all packs, all enabled regions
Kulshan Report --quick                           # 3 regions
Kulshan Report --format html -o report.html      # HTML output
```

A per-pack-only CLI (`Kulshan scan pulse`) is not exposed today.

## Permissions

Read-only. Key actions: `cloudwatch:Describe*`, `logs:Describe*`, `cloudtrail:Describe*`, `xray:Get*`. Granular per-pack policy at [`kulshan/iam/per-check/pulse.json`](../../kulshan/iam/per-check/pulse.json).

## Cost

$0.
