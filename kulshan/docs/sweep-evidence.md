# Sweep evidence and financial meaning

Sweep produces observations and investigation candidates, never authorization to remove resources.
Cleanup commands are commented, non-executing reference information requiring manual review.

## Activity observations

NAT uses `BytesOutToDestination` over 14 days; Lambda uses `Invocations` over 90 days.
The requested window ends at the last UTC midnight and includes exactly 14 or 90 closed days.
Daily Sum periods respect CloudWatch retention constraints and the 1,440-point request limit.
See [AWS GetMetricStatistics](https://docs.aws.amazon.com/AmazonCloudWatch/latest/APIReference/API_GetMetricStatistics.html).

Evidence records the requested endpoints, actual timestamps, returned datapoint count,
valid daily coverage, Sum, unit, source, and missing-data reason. Points must be distinct,
aligned, within the window, finite, nonnegative, and contain the requested statistic.
CloudWatch can return points out of order. Missing emissions are never filled with zero.

- `confirmed_observation`: all daily metric sums were observed. Zero means zero for this
  particular metric across those buckets. It says nothing about ownership or removal safety.
- `review_candidate`: configuration suggests an investigation, with historical usage,
  recovery and deployment dependencies still unverified.
- `insufficient_evidence`: missing, partial, contradictory, duplicate or malformed measurements.
- `could_not_check`: the metric request failed, including denied access and network failures.

A single positive valid observation prevents a zero-activity finding even if other periods
are missing. Incomplete metrics still make the assessment partial. Sparse Lambda metrics
will often yield insufficient evidence; infrequent and recovery workflows require owner review.

EBS creation age is not unattached duration. AMI instance references do not cover launch
templates or recovery plans. A missing snapshot source volume does not establish an obsolete
backup. Stopped databases, unhealthy targets and no current S3 objects are configuration
observations; S3 versions and dependencies are not established by a current-object listing.

## Discovery and coverage

Sweep validates inventory response lists and required dependency fields and consumes pagination.
Denied, malformed and partially paginated inventories cannot support negative membership claims.
Failures suppress only dependent classifications; other successful observations are retained.
Scanner/region execution records carry the service, operation and evidence limitation through
consolidated coverage and MCP. Incomplete assessments have no overall hygiene score or grade.
An empty result without recorded scanner completion cannot earn a perfect score.

## Financial semantics

All scanner list-price constants have been removed. No pricing API or new IAM permission is needed.
Unknown financial impact is JSON `null`, an empty numeric CSV cell, and `Unknown` in human output.
It is excluded from savings totals without claiming verified zero-dollar waste.

- `observed_billed_cost`: attributed billing evidence for an actual period, with source,
  currency and the existing `CostBasis` accounting model. It is not deletion savings.
- `estimated_cost`: requires a resource-specific regional rate, complete pricing dimensions,
  usage units and period. Sweep currently makes no such estimates.
- `potential_avoidable_cost`: requires an independently justified removal scenario. Sweep
  currently makes no such claims.
- `unknown`: sufficient billing, pricing or removal evidence is unavailable.

Programmatic `run_scan(..., financial_evidence={(region, resource_id): evidence})` can accept
already-attributed CUR or Cost Explorer evidence with `resource_id`, `region`, `source`
(`cur_parquet` or `cost_explorer`), `semantics` (`observed_billed_cost`), decimal `value`,
timezone-aware `period_start`/`period_end`, and `cost_basis` (`CostBasis` or its dictionary).
Amounts preserve decimal precision and currency. Account-level totals and generic regional
prices are rejected. The normal CLI does not have resource-attributed billing evidence and
therefore reports unknown amounts. No 730-hour normalization is represented as an invoice.

Finding evidence survives canonical conversion, JSON, CSV, HTML, SARIF and compact MCP output.
MCP continues to apply the existing fail-closed pseudonymization boundary to all new fields.
The canonical monthly-impact field now permits an explicit null; schema version remains 2.0.
