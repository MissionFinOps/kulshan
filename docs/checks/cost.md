# Cost (FinOps)

**Check pack:** `Kulshan.checks.cost`
**Orchestrator key:** `cost`
**Score weight:** 15% (see `TOOL_WEIGHTS` in `kulshan/src/kulshan/orchestrator.py`)
**IAM policy:** [`kulshan/iam/per-check/cost.json`](../../kulshan/iam/per-check/cost.json)

## What it does

Hits the Cost Explorer API directly, runs multi-method anomaly detection, scores cost efficiency 0-100, breaks down network costs, and produces timestamped reports. No CUR setup. No web server. No third-party platform.

## Key features

- Multi-dimension analysis (service, account, region, charge type, instance type, purchase option)
- Multi-method anomaly detection (Z-Score, IQR, MAD, Week-over-Week)
- RI/SP coverage and utilization analysis
- Cost forecasting with confidence bounds
- Network cost categorization (NAT, egress, cross-region, VPC endpoints)
- Idle-resource detection
- Pareto (80/20) cost distribution
- Rightsizing recommendations
- Natural-language "Cost Story" generation

## Scoring breakdown (0-100)

| Category | Points | Target |
|----------|--------|--------|
| RI/SP Coverage | 0-25 | 80%+ coverage |
| RI/SP Utilization | 0-25 | 90%+ utilization |
| Waste Detection | 0-20 | 0 idle resources |
| Anomaly Health | 0-15 | 0 critical anomalies |
| Cost Stability | 0-15 | Committed pricing |

## How to run

This pack runs as part of the unified Kulshan scan:

```bash
Kulshan Report                                   # all packs, all enabled regions
Kulshan Report --quick                           # all packs, 3 regions
Kulshan Report --days 90                         # 90-day cost lookback window
Kulshan Report --format html -o report.html      # HTML output
Kulshan Report --format json -o report.json      # JSON output
```

A per-pack-only CLI (`Kulshan scan cost`) is not exposed today.

## Permissions

- Minimum: `ce:GetCostAndUsage` + `ce:GetCostForecast`
- Full: AWS managed `AWSBillingReadOnlyAccess`
- Granular: see [`kulshan/iam/per-check/cost.json`](../../kulshan/iam/per-check/cost.json)

Optional permissions degrade gracefully: missing actions are silently skipped.

## API cost

~$0.15–$0.20 per full run (15–20 Cost Explorer API calls at $0.01 each).

## Network cost categories

- NAT Gateway
- VPC Endpoints
- Internet Egress
- Inter-Region Transfer
- Transit Gateway
- Cloud WAN
- Network Firewall
- Route 53 / DNS
