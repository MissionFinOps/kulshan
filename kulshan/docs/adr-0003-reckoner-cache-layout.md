# ADR 0003: Reckoner physical cache benchmark and decision

Status: Accepted for the PR 3 benchmark baseline
Date: 2026-07-28

## Context

The Reckoner Engine needs a local analytical cache, but choosing table layout from intuition risks incorrect refresh and query tradeoffs. PR 3 measures two bounded candidate layouts against equivalent synthetic daily cost facts.

Candidate A uses daily cost facts plus monthly, commitment, and allocation relations. Candidate B separates daily usage and commitment facts and retains monthly and allocation relations. Workloads cover major dimensions, three-dimensional comparisons, and 18-period trends.

## Decision

The benchmark harness is the source of the decision, not a production cache. On the checked-in 1,000-row synthetic run (two repetitions), Candidate B had the lower mean workload p95 and was selected by the scoring function. If candidates differ by less than 10 percent, the harness selects Candidate A for physical simplicity.

The result is provisional until representative local samples, legacy CUR, CUR 2.0, schema eras, enterprise account cardinalities, commitments, transfer, incremental refresh, and historical correction workloads are benchmarked. The harness records measurements and rationale so those runs are repeatable.

## Constraints

No cache tables are shipped or materialized by this PR. No Parquet is downloaded, no S3 bytes are read, and no query planner or refresh engine is implemented. Database-size and refresh measurements are represented in the measurement contract and will be populated by representative benchmark runs before PR 4.

The next boundary may implement the selected physical design only after validating equivalence, partition refresh behavior, and the locked p95/size/refresh score weights (35%, 30%, 20%, 15%).