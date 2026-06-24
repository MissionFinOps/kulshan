# CUR Automation And Athena Research

Read this before building `kulshan cur discover`, `kulshan cur inspect`, `kulshan cur sample`, or `kulshan investigate ... --cur auto`.

## Research question

What is the easiest, simplest, most automated UX for getting AWS CUR / Data Exports evidence into Kulshan?

The answer is not local-only and not Athena-only. Kulshan should support a hybrid execution model:

```text
AWS billing export discovery
  -> S3 evidence location
  -> Glue/Athena path when already available
  -> local sampling + DuckDB path when Glue/Athena is absent or slower
  -> same evidence packet
  -> same investigation brief
```

Product rule:

> Kulshan should not require Glue, Athena, QuickSight, or S3 Tables, but it should use Glue Catalog and Athena when they already exist and improve the user path.

## Target UX

Best case:

```bash
kulshan investigate ec2 --cur auto
```

Expanded flow:

```bash
kulshan cur discover
kulshan cur inspect --cur auto
kulshan cur sample --cur auto --months 2
kulshan investigate ec2 --cur auto
```

Execution selection:

```bash
kulshan investigate ec2 --cur auto --engine auto
kulshan investigate ec2 --cur auto --engine local
kulshan investigate ec2 --cur auto --engine athena
```

`--engine auto` should choose the lowest-friction path that can produce the evidence packet.

## Why Athena must be first-class

Many AWS cost teams already have the CUDOS-style stack:

```text
CUR / Data Exports
  -> S3
  -> Glue crawler
  -> Glue Data Catalog
  -> Athena
  -> QuickSight
```

Kulshan should be able to run serverless investigation queries against that stack out of the box. This is especially useful when:

- The CUR is too large to download quickly.
- A Glue table already exists.
- Athena workgroups and query result buckets are already configured.
- The user wants a one-off investigation and accepts Athena scan cost.
- The organization already trusts the Glue/Athena metadata path.

Kulshan should still produce a brief, not a dashboard.

## Execution modes

### Local mode

```text
S3 CUR/Data Export
  -> selective local sample
  -> local Parquet cache
  -> DuckDB
  -> evidence packet
```

Use local mode when:

- No Glue table exists.
- Athena permissions are missing.
- The latest two periods are small enough to sample.
- The user wants local replay or offline work.
- Repeat investigations make caching valuable.

### Athena mode

```text
S3 CUR/Data Export
  -> Glue Catalog table
  -> Athena SQL
  -> evidence packet
```

Use Athena mode when:

- A matching Glue table already exists.
- The account already has Athena query output configured.
- The export is large.
- Downloading local data would be slower or more expensive than serverless query.

### Auto mode

Default selection:

```text
if fresh local cache exists:
    use local DuckDB
elif matching Glue table and Athena workgroup are usable:
    use Athena
elif S3 prefix is readable:
    sample latest periods locally and use DuckDB
else:
    print missing permissions and setup guidance
```

## Discovery layer

Always try all discovery paths and collect diagnostics. Do not stop after one access denied.

Discovery order:

```text
1. sts:GetCallerIdentity
2. bcm-data-exports:ListExports
3. bcm-data-exports:GetExport
4. cur:DescribeReportDefinitions
5. user-provided s3:// path
6. user-provided local path
```

Candidate fields:

```text
kind                 # data_export | legacy_cur | manual_s3 | local
name
account_id
bucket
prefix
region
format
compression
status
last_delivery
has_resource_ids
score
permission_errors
```

Scoring:

```text
+50 PARQUET / Parquet
+25 HEALTHY or last delivery success
+20 resource IDs available
+15 recent delivery or recent objects
+10 Data Exports / CUR 2.0
+10 matching Glue table exists
+5 Athena workgroup usable
-50 CSV/GZIP only
-100 unhealthy destination or no readable S3 prefix
```

## Glue/Athena readiness checks

Given a discovered S3 export candidate, Kulshan should check whether Athena can already query it.

Checks:

```text
1. List Glue databases.
2. List/Get Glue tables.
3. Find tables whose StorageDescriptor.Location overlaps the CUR S3 prefix.
4. Confirm table input/output formats are Parquet-compatible or table parameters indicate Parquet.
5. Confirm partition columns or data columns expose billing periods.
6. Confirm an Athena workgroup is available.
7. Confirm Athena query result output location is configured or discoverable.
8. Run a cheap validation query with LIMIT 1 or metadata-only query if possible.
```

Do not create a crawler, Glue table, Athena workgroup, or result bucket by default. Kulshan is read-only by default.

## Athena permissions

Athena mode likely needs:

```text
athena:ListWorkGroups
athena:GetWorkGroup
athena:StartQueryExecution
athena:GetQueryExecution
athena:GetQueryResults

glue:GetDatabases
glue:GetDatabase
glue:GetTables
glue:GetTable
glue:GetPartitions

s3:ListBucket          # CUR bucket/prefix and Athena result bucket
s3:GetObject           # CUR objects and Athena result objects
s3:PutObject           # Athena query result output bucket, if Athena writes results there
```

`athena` mode may violate a strict read-only mental model because Athena writes query results to S3. Product copy must be explicit:

```text
Athena mode does not modify AWS resources, but Athena writes query result files to the configured query result bucket.
```

For strict local read-only behavior, use local mode.

## Local mode permissions

Local sampling needs:

```text
s3:ListBucket
s3:GetObject
```

Discovery adds:

```text
sts:GetCallerIdentity
cur:DescribeReportDefinitions
bcm-data-exports:ListExports
bcm-data-exports:GetExport
```

## Replacing Glue crawler locally

Glue crawler responsibilities:

```text
find files
infer schema
infer partitions
group files into tables
write metadata to Glue Catalog
```

Kulshan local replacement:

```text
find files              -> S3 ListObjectsV2
infer schema            -> Parquet footer / DuckDB DESCRIBE
infer partitions        -> object key parser + row inspection
group files             -> local export manifest
write metadata          -> SQLite source catalog
```

This is enough for Kulshan's investigation queries.

## Replacing Glue Catalog locally

Glue Catalog responsibilities:

```text
table location
schema
partitions
query engine metadata
```

Kulshan local catalog:

```text
.kulshan/sources.sqlite
.kulshan/cur/<account>/<export>/manifest.json
.kulshan/cur/<account>/<export>/<period>/*.parquet
```

SQLite tables:

```sql
exports(
  id,
  account_id,
  kind,
  name,
  bucket,
  prefix,
  region,
  format,
  compression,
  status,
  selected,
  discovered_at
);

objects(
  id,
  export_id,
  key,
  local_path,
  size_bytes,
  etag,
  last_modified,
  inferred_period,
  downloaded_at
);

schemas(
  id,
  export_id,
  fingerprint,
  detected_at
);

columns(
  schema_id,
  source_name,
  semantic_name,
  source_type,
  required
);

athena_tables(
  id,
  export_id,
  database_name,
  table_name,
  location,
  workgroup,
  verified_at
);
```

## Query contract

Local and Athena engines must produce the same evidence packet.

Required EC2 evidence:

```text
previous_period
current_period
previous_cost
current_cost
delta
delta_percent
top_resources
top_usage_types
review_questions
warnings
engine_metadata
```

The Python renderer must not care whether the evidence came from DuckDB or Athena.

## SQL normalization

Both engines should implement the same semantic mapping.

Semantic fields:

```text
usage_start
billing_period
service
usage_type
resource_id
cost
account_id
region
```

Cost precedence for MVP:

```text
line_item_net_unblended_cost
line_item_unblended_cost
line_item_blended_cost
cost
```

Period rule:

```text
Use the two latest YYYY-MM periods present after filtering to EC2 rows.
```

Warning:

```text
If the current period appears partial, include latest_period_may_be_partial.
```

Ordering rule:

```text
ORDER BY delta DESC, current_cost DESC, name ASC
```

## Athena query shape

Use the Glue table as raw CUR and generate normalized SQL around detected column names.

Totals:

```sql
SELECT
  period,
  SUM(cost) AS total_cost
FROM normalized_cur
WHERE service_is_ec2
GROUP BY period
ORDER BY period DESC
LIMIT 2;
```

Top resources:

```sql
SELECT
  resource_id,
  SUM(CASE WHEN period = :previous THEN cost ELSE 0 END) AS previous_cost,
  SUM(CASE WHEN period = :current THEN cost ELSE 0 END) AS current_cost
FROM normalized_cur
WHERE service_is_ec2
  AND period IN (:previous, :current)
GROUP BY resource_id
ORDER BY current_cost - previous_cost DESC, current_cost DESC, resource_id ASC
LIMIT 5;
```

Top usage types use the same shape grouped by usage type.

## Performance research

Measure local and Athena paths side by side.

Dimensions:

```text
first-run time
repeat-run time
bytes downloaded
bytes scanned
query cost
local disk used
peak memory
number of S3 requests
number of Athena queries
failure clarity
```

Datasets:

```text
small lab account
medium synthetic export
large real or generated multi-month export
existing CUDOS/Athena setup if available
no-Glue setup
```

Expected performance profile:

```text
local sample + DuckDB
  better for repeat use, offline replay, smaller accounts, strict read-only users

Athena
  better for large exports, existing Glue tables, and one-off serverless query
```

Auto mode should not assume. It should measure or estimate:

```text
local download estimate = selected object size
Athena scan estimate = referenced columns over selected partitions if known, otherwise conservative object size estimate
```

## Cost UX

Before Athena queries that may scan meaningful data:

```text
Athena mode will run 3 queries against workgroup primary.
Estimated scan: 8.2 GB.
Estimated Athena cost: under $0.05, plus S3 request/result storage costs.
Proceed? [y/N]
```

Use `--yes` for CI and automation.

Before local sampling:

```text
Local mode will download 16 Parquet files.
Estimated download: 420 MB.
Destination: .kulshan/cur/166484409834/lab-cur2/
Proceed? [y/N]
```

## S3 database-like capabilities

### S3 Tables / Iceberg

S3 Tables are a future optional enterprise path, not MVP default.

Use later when Kulshan needs:

```text
shared normalized billing table
multi-user query layer
managed compaction
Iceberg snapshots
Athena/Redshift/Spark interoperability
```

Do not require S3 Tables for the first automated UX because they add AWS-side setup, new IAM namespace, and likely write/transform workflows.

### S3 Inventory and S3 Metadata

Use as optional object discovery accelerators.

Default:

```text
ListObjectsV2
```

If Inventory/Metadata exists:

```text
read object manifest from S3 Inventory or S3 Metadata tables
avoid expensive prefix listing
use object size/last modified metadata to choose sample periods
```

They do not replace querying CUR rows.

### S3 Select

Do not use as a new foundation. It is not available to new customers and only queries one object per request.

## Research experiments

### Experiment 1: lab account discovery

Run with the user's real lab account:

```bash
kulshan cur discover --debug
```

Capture:

```text
which APIs are allowed
which exports exist
which permissions are missing
which S3 prefixes are readable
```

### Experiment 2: Athena table matching

Given discovered export prefixes:

```bash
kulshan cur athena-check --cur auto
```

Capture:

```text
matching Glue databases/tables
workgroups
query result locations
validation query success/failure
```

### Experiment 3: local vs Athena parity

For the same export and same periods:

```bash
kulshan investigate ec2 --cur auto --engine local --json
kulshan investigate ec2 --cur auto --engine athena --json
```

Outputs must match on cost fields and rankings, except engine metadata.

### Experiment 4: performance and cost

Record:

```text
local sample download seconds
local query seconds
Athena queue seconds
Athena execution seconds
Athena bytes scanned
Athena estimated cost
repeat local query seconds
```

### Experiment 5: failure UX

Test:

```text
no CUR permission
no Data Exports permission
no S3 list
no S3 get
no Glue read
no Athena result bucket write
no Athena workgroup
multiple candidate exports
CSV-only export
one month only
```

Each case should produce a next action.

## Implementation order

1. `kulshan cur discover`
2. `kulshan cur inspect --cur auto`
3. `kulshan cur athena-check --cur auto`
4. `kulshan cur sample --cur auto --months 2`
5. `kulshan investigate ec2 --cur auto --engine local`
6. `kulshan investigate ec2 --cur auto --engine athena`
7. `kulshan investigate ec2 --cur auto --engine auto`
8. Optional S3 Inventory / S3 Metadata acceleration
9. Optional S3 Tables / Iceberg enterprise mode

## Decision

Build both local and Athena support, but keep the same evidence contract.

Default philosophy:

```text
Athena when AWS-native metadata already exists and is cheaper/faster.
Local DuckDB when setup is missing, repeatability matters, or strict local-first behavior is preferred.
```

This gives Kulshan an out-of-the-box path for CUDOS/Athena users without making Glue/Athena mandatory.

## Athena performance design details

Athena mode must be cost-aware and metadata-aware. It should not blindly run queries just because a Glue table exists.

### Use workgroup controls as safety rails

Athena workgroups separate workloads, control access, enforce settings, track metrics, and control costs. Each account has a `primary` workgroup, but organizations may have dedicated workgroups for ad hoc analytics, BI, or automation.

Kulshan should:

```text
1. Prefer a user-provided --athena-workgroup.
2. Otherwise inspect accessible workgroups.
3. Fall back to primary only if accessible and configured.
4. Display the workgroup before running queries.
5. Respect workgroup-enforced result configuration.
```

Athena workgroups can have per-query data scanned limits that cancel queries over a configured threshold. Kulshan should surface this if available and treat query cancellation as a cost-safety result, not an opaque failure.

### Use GetQueryExecution for measured performance

After each Athena query, call `GetQueryExecution` and record:

```text
DataScannedInBytes
EngineExecutionTimeInMillis
QueryPlanningTimeInMillis
QueryQueueTimeInMillis
TotalExecutionTimeInMillis
ResultReuseInformation.ReusedPreviousResult
Status.State
Status.StateChangeReason
Status.AthenaError
ResultConfiguration.OutputLocation
WorkGroup
```

These fields allow Kulshan to show real performance and cost evidence:

```text
Athena query complete.
Data scanned: 1.2 GB
Execution: 4.1s
Planning: 0.8s
Queue: 0.2s
Estimated Athena cost: <$0.01
Result reuse: no
```

This is also the basis for local-vs-Athena benchmarking.

### Use result reuse carefully

Athena can reuse previous query results when query string, catalog/database, result configuration, permissions, and other conditions match. This can reduce cost and latency for repeat investigations.

Kulshan should support:

```bash
kulshan investigate ec2 --cur auto --engine athena --reuse-results 60
```

Default recommendation:

```text
Do not enable result reuse by default for investigation briefs unless the user explicitly opts in or the cache age is clearly displayed.
```

Reason: billing data may refresh, and stale results are dangerous in an evidence brief.

If enabled, the evidence packet must include:

```json
"athena": {
  "result_reuse_enabled": true,
  "result_reused": true,
  "max_age_minutes": 60
}
```

### Partition projection can replace partition crawling in Athena mode

Athena partition projection can speed highly partitioned tables and automate partition management by using table properties in Glue instead of retrieving partition metadata from the Glue Catalog. Athena normally calls `GetPartitions`; partition projection can avoid that by calculating partitions from configured rules.

This matters for CUR because billing data is time-oriented and often partitioned by period/date/export path.

Research question:

```text
Can Kulshan detect whether a Glue table uses partition projection, and can it generate better predicates for projected partitions?
```

Detection:

```text
Glue table Parameters contains projection.enabled=true
projection.<partition>.type
projection.<partition>.range
storage.location.template
```

Kulshan should not create or modify projection settings by default, but should recognize them and use equality predicates on partition keys where possible.

### Query partition keys by equality where possible

Athena guidance favors predicates on partition keys. For EC2 investigation, Kulshan should first determine the latest two periods, then query exact partition values rather than broad ranges.

Preferred pattern:

```sql
WHERE billing_period IN ('2026-05', '2026-06')
```

Avoid:

```sql
WHERE billing_period >= '2026-05'
```

unless no discrete partitions are available.

### Parquet and column pruning are mandatory for Athena UX

Athena is billed by data scanned. CUR should be Parquet for Athena mode because columnar files allow Athena to read only referenced columns. Kulshan's EC2 investigation SQL should reference only required columns:

```text
usage start / billing period
service
usage type
resource id
cost
partition columns
```

Do not `SELECT *` in Athena except for tiny validation probes with `LIMIT 1`, and even then prefer schema metadata or table columns from Glue.

### Beware many small files

Athena performance degrades with many small files because planning/listing and per-file overhead dominate. CUR exports can contain many files depending on size, refresh behavior, and report versioning.

Kulshan should collect:

```text
file_count
small_file_count_under_8mb
median_file_size
partition_file_counts
```

If file count is high, show a warning:

```text
Athena may be slower because this export has 3,200 small Parquet files.
Local sampling may be faster for a two-month investigation.
```

Future enterprise fix:

```text
S3 Tables / Iceberg or compaction pipeline
```

MVP fix:

```text
local sampling + DuckDB over selected periods
```

### Athena can write partial result artifacts

Athena writes query results to S3. Failed or canceled queries may leave partial result artifacts or incomplete multipart uploads. Product copy must be honest:

```text
Athena mode is read-only for billing source data, but it writes query result files to the configured Athena result bucket.
```

Strict local-first users should use:

```bash
--engine local
```

## Athena table matching algorithm

Given a discovered CUR export candidate:

```text
bucket = billing-export-bucket
prefix = exports/cur2/
```

Find matching Glue tables:

```text
1. Enumerate accessible Glue databases.
2. Enumerate tables in each database.
3. Read StorageDescriptor.Location.
4. Normalize S3 URI.
5. Score overlap:
   - exact prefix match
   - table location is parent of export prefix
   - export prefix is parent of table location
   - table name contains cur/cudos/cid/billing/cost
6. Inspect columns and partition keys for CUR-like fields.
7. Prefer tables with Parquet input format / SerDe / parameters.
```

Table score:

```text
+40 location overlaps discovered export prefix
+30 has required CUR semantic columns
+20 Parquet table
+15 has billing period/date partition
+10 projection.enabled=true
+10 table name hints cur/cudos/cost/billing
-50 missing cost column
-50 missing usage date/period column
-50 CSV table for Athena MVP
```

If multiple tables tie, require explicit selection:

```bash
kulshan investigate ec2 --cur auto --athena-table database.table
```

## Athena validation query ladder

Do not start with full investigation queries. Use progressively stronger checks.

1. Metadata check only:

```text
Glue GetTable columns and partitions
```

2. Cheap row check:

```sql
SELECT 1
FROM database.table
LIMIT 1
```

3. EC2 presence check:

```sql
SELECT COUNT(*)
FROM database.table
WHERE service_is_ec2
LIMIT 1
```

4. Period check:

```sql
SELECT period, SUM(cost)
FROM normalized_table
WHERE service_is_ec2
GROUP BY period
ORDER BY period DESC
LIMIT 2
```

Only then run top resource and usage type queries.

## Local performance design details

Local mode should optimize for repeat investigation and debuggability.

### Local catalog replaces repeated S3 listing

On first run, list S3 objects and write to SQLite. On later runs, use cached object metadata unless:

```text
--refresh
export last delivery changed
object count changed
latest object modified after cached manifest
```

### Local sample should be period-aware

Do not download every object. The sampler should choose:

```text
latest complete previous period
current/latest period
only Parquet objects
only objects under selected period-like prefixes when possible
```

If period inference from paths is uncertain, sample footers/limited rows to map periods.

### Local DuckDB query should be one pass where possible

The EC2 investigation can be computed with one normalized scan using grouping sets or separate grouped queries over the same filtered CTE. Avoid re-reading all Parquet files for each table if DuckDB does not cache enough automatically.

Candidate shape:

```sql
WITH ec2 AS (
  SELECT period, resource_id, usage_type, cost
  FROM cur_normalized
  WHERE service_is_ec2
), periods AS (...), selected AS (...)
SELECT ...
```

Research whether DuckDB materialized temp tables improve repeat subqueries:

```sql
CREATE TEMP TABLE ec2_selected AS
SELECT ...
```

This may be faster for brief generation because totals, resources, and usage types all reuse the same slice.

### Local performance metrics

Record:

```text
s3_list_seconds
selected_file_count
selected_bytes
download_seconds
schema_inspect_seconds
duckdb_query_seconds
rows_scanned if available
local_cache_hit
```

## Auto engine decision model

Kulshan should make the decision explicit and explainable.

Inputs:

```text
local_cache_fresh
local_selected_bytes
athena_table_available
athena_workgroup_available
athena_result_bucket_writable
athena_estimated_scan_bytes
user_engine_preference
strict_read_only_mode
```

Decision:

```text
if user selected local:
    local
elif user selected athena:
    athena
elif strict_read_only_mode:
    local
elif fresh local cache exists:
    local
elif athena_ready and local_selected_bytes > 1GB:
    athena
elif s3_readable:
    local sample
elif athena_ready:
    athena
else:
    fail with permission/setup ladder
```

The 1GB threshold is a starting hypothesis, not a final value. Research should measure it.

## Open research questions

1. What exact Glue table shapes do AWS CUR Athena CloudFormation and CUDOS create?
2. Do Data Exports CUR2 tables have predictable partition columns?
3. Can `EXPLAIN` estimate partitions/files scanned cheaply enough to use before running Athena queries?
4. Does Athena result reuse help investigation UX, or does stale-data risk outweigh it?
5. At what selected byte size does Athena beat local download + DuckDB for first run?
6. At what selected byte size does local cache beat Athena for repeat runs?
7. Can Kulshan safely infer current-period partialness from CUR object dates and row dates?
8. Should Kulshan create a dedicated Athena workgroup only in an explicit setup command, never in investigate?
9. How common are Lake Formation restrictions in target accounts, and how do they affect result reuse and table access?
10. How should Kulshan quote/escape Glue table and column names generated by CUR/CUDOS?

## AWS CUR Athena integration specifics

AWS' own CUR Athena setup is important because Kulshan should detect and work with it when present.

AWS documents the CUR/Athena path as:

```text
CUR in S3
  -> Athena integration CloudFormation template
  -> Glue database
  -> Glue crawler
  -> Lambda functions
  -> S3 notification
  -> Athena table
```

The CloudFormation template created by AWS includes:

```text
three IAM roles
one Glue database
one Glue crawler
two Lambda functions
one S3 notification
```

Important UX caveat: AWS warns that the Athena CloudFormation setup can remove existing S3 events on the report bucket. Kulshan must not run this setup automatically. If Kulshan ever offers setup help, it should generate instructions and warn about S3 notification side effects.

## CUR Athena table status

AWS' Athena setup includes a status table/query pattern:

```sql
SELECT status FROM cost_and_usage_data_status;
```

Possible statuses:

```text
READY
UPDATING
```

If status is `UPDATING`, Athena may return incomplete results. Kulshan Athena mode should check this table when it exists.

Behavior:

```text
if cost_and_usage_data_status exists and status = UPDATING:
    warn current data may be incomplete
    require --yes or continue with warning
```

Evidence packet warning:

```json
"warnings": ["cur_status_updating"]
```

## CUR Athena column name normalization

AWS changes CUR column names when loading CUR into Athena:

```text
uppercase letters get underscores and become lowercase
non-alphanumeric characters become underscores
duplicate underscores are removed
leading/trailing underscores are removed
very long names may have underscores removed
some resource tag duplicate names may be merged
```

Example:

```text
ExampleColumnName -> example_column_name
Example Column Name -> example_column_name
```

This means Kulshan cannot assume local Parquet column names and Athena table column names are identical.

The schema normalizer must support both:

```text
local/Data Export-style names
Athena-normalized names
```

For MVP, semantic aliases should include:

```text
usage_start:
  line_item_usage_start_date
  lineitem_usagestartdate
  usage_start_date

service:
  line_item_product_code
  product_servicecode
  product_product_name
  service

usage_type:
  line_item_usage_type
  lineitem_usagetype
  usage_type

resource_id:
  line_item_resource_id
  lineitem_resourceid
  resource_id

cost:
  line_item_net_unblended_cost
  line_item_unblended_cost
  line_item_blended_cost
  lineitem_unblendedcost
  cost
```

Athena mode should derive aliases from Glue columns, not from Parquet files.

## Athena CUR table discovery heuristics

Known hints for AWS-generated CUR Athena integration:

```text
Glue database created by AWS CUR Athena CloudFormation
Glue crawler tied to the CUR report bucket/prefix
Athena table with many line_item_* columns
possible cost_and_usage_data_status table
partition columns such as year/month or billing period fields
```

Kulshan should score a Glue database/table higher if:

```text
same database contains cost_and_usage_data_status
main table contains line_item_product_code
main table contains line_item_blended_cost or line_item_unblended_cost
main table contains month/year columns or partition keys
StorageDescriptor.Location overlaps the discovered CUR S3 prefix
```

## Athena setup modes

Kulshan should distinguish three Athena cases:

### 1. Existing Athena-ready setup

```text
Glue table exists
Athena workgroup exists
result output location works
CUR status is READY or status table absent
```

Use it.

### 2. Export exists but Athena setup absent

```text
CUR/Data Export S3 prefix exists
no matching Glue table
```

Default to local DuckDB sampling.

Show optional guidance:

```text
No matching Glue table found. Kulshan can query locally now.
For AWS-native Athena mode, set up CUR Athena integration or create a Glue table for this prefix.
```

### 3. Athena setup exists but is unsafe or incomplete

Examples:

```text
status = UPDATING
workgroup disabled
no query result bucket
missing s3:PutObject on result bucket
Glue table points to stale prefix
CSV table only
```

Default to local if possible. Otherwise emit exact next action.

## Athena result write semantics

Athena mode is not pure read-only from an AWS API perspective because query results are written to S3. It is read-only with respect to billing source data, but not read-only with respect to the account.

Product language:

```text
Athena mode reads billing data from S3 and writes query results to the configured Athena result bucket. Use --engine local for strict local-only execution after sampling.
```

This matters because Kulshan's brand promise is read-only AWS audit. The safe phrasing is:

```text
Kulshan never modifies billing exports or AWS resources. Athena itself may write query result files to your Athena results bucket.
```

## Athena query result controls

For Athena mode, Kulshan should expose:

```bash
--athena-workgroup <name>
--athena-output s3://bucket/prefix/    # optional, only if workgroup does not enforce output
--athena-max-scan-gb <n>
--reuse-results <minutes>
```

Default:

```text
reuse disabled
max scan warning threshold low, e.g. 5 GB until measured
prompt unless --yes
```

If workgroup enforces configuration, Kulshan should not try to override output location.

## Serverless Athena UX

Best Athena UX:

```bash
kulshan investigate ec2 --cur auto --engine athena
```

Step output:

```text
Found CUR export: lab-cur2
Matched Glue table: cid.cur2_parquet
Athena workgroup: primary
CUR status: READY
Planned queries: 3
Estimated scan: unknown before first run
Proceed? [y/N]
```

After run:

```text
Athena metrics:
- data scanned: 742 MB
- total time: 6.3s
- engine time: 4.9s
- planning time: 0.7s
- queue time: 0.1s
- result reuse: no
```

Store these metrics in the evidence packet and local history.

## Local vs Athena performance hypotheses

Hypotheses to test:

1. For under 500 MB selected Parquet, local sample + DuckDB is usually better after first download.
2. For large CUR prefixes with existing Glue tables, Athena is usually better for first-run investigations.
3. For repeated investigations on the same two periods, local cache is usually better regardless of first-run cost.
4. If Athena table has poor partitioning or many tiny files, local sampling may outperform Athena.
5. If local download bandwidth is poor, Athena may win even for medium exports.
6. If current period is updating, both engines can produce incomplete answers; the issue is source freshness, not engine choice.

## Benchmark plan

For every real or synthetic dataset, run:

```bash
kulshan investigate ec2 --cur <source> --engine local --json
kulshan investigate ec2 --cur <source> --engine athena --json
```

Collect:

```text
engine
first_run_wall_seconds
repeat_run_wall_seconds
bytes_downloaded
bytes_scanned
athena_cost_estimate
s3_request_count if available
query_result_reused
brief_matches
warnings
```

Acceptance:

```text
same previous/current cost
same delta percent after rounding
same top resource ordering
same top usage type ordering
same warning semantics where applicable
```

## Research conclusion so far

Athena support should be built as an execution engine, not as a setup dependency.

Do:

```text
Detect existing Glue/Athena setup.
Use it when it is ready and advantageous.
Measure bytes scanned and time.
Return the same evidence packet as local mode.
```

Do not:

```text
Run CUR Athena CloudFormation automatically.
Create Glue crawlers by default.
Modify S3 notifications.
Require QuickSight/CUDOS.
Assume Athena is read-only without explaining result writes.
```

## AWS Data Exports / CUR 2.0 discovery specifics

AWS Data Exports has its own metadata APIs that are useful before looking at S3 or Glue.

Useful read-only APIs:

```text
bcm-data-exports:ListExports
bcm-data-exports:GetExport
bcm-data-exports:ListTables
bcm-data-exports:GetTable
bcm-data-exports:ListExecutions
```

`ListTables` lists available Data Exports tables and their properties. `GetTable` returns metadata for a specified table, including schema columns, data types, and descriptions. This is valuable because Kulshan can learn CUR2 schema and table properties directly from Billing and Cost Management APIs instead of relying only on Glue or Parquet inspection.

`CreateExport` is not part of default Kulshan investigation, but its API docs clarify the model:

```text
DataQuery = QueryStatement + TableConfigurations
QueryStatement = limited SQL
TableConfigurations = table-specific properties
```

Kulshan should use this knowledge to inspect exports, not to create them by default.

## Data Exports table dictionary as schema source

For Data Exports, Kulshan should use this schema priority:

```text
1. GetExport DataQuery.QueryStatement and TableConfigurations
2. GetTable schema for referenced table names
3. S3 Parquet schema inspection
4. Glue table schema if Athena path exists
```

This gives better diagnostics:

```text
Your Data Export query does not include resource_id, so Kulshan can show usage-type deltas but not resource-level contributors.
```

or:

```text
Your export table supports resource_id, but the configured QueryStatement does not select it.
```

## Data Exports execution state

Research `ListExecutions` for each export and capture:

```text
latest execution status
latest completed delivery time
latest failed reason if any
execution output location if exposed
```

Use this in `cur discover`:

```text
Data Export: lab-cur2
Status: HEALTHY
Latest execution: SUCCEEDED 2026-06-23 04:12 UTC
Destination: s3://bucket/prefix/
```

If latest execution failed or is stale:

```text
Export exists but latest delivery is not healthy. Investigation may use stale billing data.
```

## Safe setup guidance, not automatic creation

Kulshan should eventually provide:

```bash
kulshan cur setup-plan
```

This command should not create AWS resources by default. It should generate a plan:

```text
Recommended setup:
- AWS Data Export / CUR 2.0
- PARQUET output
- S3 destination: user-provided bucket/prefix
- Include resource IDs if available
- Overwrite or create-new-report: explain tradeoff
- Optional Athena/Glue setup: manual or CloudFormation, warning about S3 notifications
```

Possible output artifacts:

```text
IAM policy snippet
AWS CLI create-export skeleton
CloudFormation warning notes
S3 bucket policy checklist
Athena setup checklist
```

Do not run:

```text
bcm-data-exports:CreateExport
cloudformation:CreateStack
glue:CreateCrawler
glue:CreateDatabase
s3:PutBucketNotification
```

inside ordinary investigation commands.

If setup automation is later added, it must be explicit:

```bash
kulshan cur setup --apply
```

and clearly outside read-only investigation mode.

## Export configuration scoring for investigation quality

Not every export is equally useful for Kulshan.

Score exports on investigation usefulness:

```text
+50 PARQUET output
+30 includes resource-level fields
+25 includes line item usage start/date fields
+25 includes unblended or net unblended cost
+15 includes account and region fields
+10 latest execution succeeded
+10 Athena/Glue table already exists
-50 CSV/text output
-50 no resource IDs
-75 no cost field
-75 no date/period field
-100 no readable S3 destination
```

UX:

```text
Best export for EC2 investigation: lab-cur2
Reason:
- PARQUET output
- resource IDs included
- latest execution succeeded
- readable S3 destination
```

If no strong export exists:

```text
Kulshan found billing exports, but none are ideal for resource-level investigation.
Best available: lab-summary-export
Limitation: no resource_id column, resource contributors unavailable.
```

## Data Exports vs legacy CUR behavior in Kulshan

Preferred discovery order should be Data Exports first, then legacy CUR, because Data Exports exposes richer table/query metadata.

However, preferred execution should still be evidence-driven:

```text
A legacy CUR Parquet export with resource IDs and existing Athena table may beat a CUR2 export that lacks resource fields.
```

So ranking should evaluate capabilities, not brand-newness.

## Setup personas

Kulshan should support these real-world states:

### Persona A: Local-only user with export but no AWS analytics stack

```text
Data Export exists
S3 readable
No Glue table
No Athena setup
```

Best path:

```text
sample locally -> DuckDB
```

### Persona B: CUDOS/CID user

```text
CUR exists
Glue table exists
Athena workgroup exists
QuickSight maybe exists
```

Best path:

```text
Athena first for large exports, local cache optional
```

### Persona C: Least-privilege audit user

```text
No discovery permissions
S3 path manually supplied
S3 read allowed
```

Best path:

```text
manual --cur s3://... or local path -> inspect/sample/query
```

### Persona D: No export yet

```text
Cost Explorer works
No CUR/Data Export
```

Best path:

```text
explain setup plan, fallback to Cost Explorer if command supports it
```

## Research: direct Athena without crawler?

Question:

```text
Can Kulshan query an S3 Parquet export with Athena without a crawler by generating a temporary external table DDL?
```

Technically possible in Athena, but it requires writes to Glue/Athena metadata and therefore violates read-only default.

Recommended stance:

```text
Do not create temporary external tables during investigate.
```

Possible explicit command later:

```bash
kulshan cur athena-bootstrap --cur auto --database kulshan_cur --table cur2 --apply
```

But this is setup, not investigation.

## Research: direct DuckDB over S3

Direct DuckDB-over-S3 may be the best middle ground after local sampling:

```text
No Glue catalog
No Athena result writes
No full local download
Still local query engine
```

Research tasks:

```text
Can DuckDB httpfs use the same boto3/AWS credential chain reliably on Windows?
Can it read selected S3 Parquet objects by explicit URI list?
Does it handle requester pays / SSE-KMS / bucket owner constraints?
How does it perform versus local sample and Athena?
Can it avoid broad S3 glob/list operations by using Kulshan's object manifest?
```

Potential execution modes become:

```text
local-cache     downloaded Parquet + DuckDB
local-s3        DuckDB reads explicit S3 object list
athena          Glue table + Athena SQL
```

Auto order may become:

```text
fresh local cache
Athena if ready and large
DuckDB direct S3 if credentials work and selected objects are moderate
local sample fallback
```

## Updated execution matrix

| Mode | Needs Glue | Writes AWS | Downloads data | Best for |
| --- | --- | --- | --- | --- |
| local-cache | No | No | Yes | repeat investigations, strict local-first |
| local-s3 DuckDB | No | No | Streams reads | no Glue, avoid full download |
| athena | Yes | Writes query results | No | existing CUDOS/Athena, large exports |
| setup/bootstrap | Creates Glue/Athena resources | Yes | No | explicit setup only |

## Product guardrails

1. Investigation commands should never create AWS resources.
2. `--engine athena` must disclose query result writes.
3. `--engine local` must remain available for strict local-first behavior.
4. `--cur auto` must explain why it chose an engine.
5. All engines must emit the same evidence contract.
6. Setup automation must be explicit and separate from investigation.
