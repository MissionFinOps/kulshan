# Kulshan Scan Performance Audit

Date: 2026-06-23

## Executive finding

Kulshan is slow because the scanner is dominated by serial AWS API I/O, not Python CPU.

Rewriting hot paths in Rust, C, or assembly will not materially improve the current worst cases. The code spends most wall time waiting on AWS control-plane APIs, paginators, explicit sleeps, CloudFormation drift polling, Service Quotas enumeration, CloudWatch metric calls, and per-bucket/per-resource loops.

The right FFmpeg-style move is a pipeline scheduler:

- bounded parallelism by region and independent pack
- shared inventory collected once and reused by packs
- fast/default scan profile versus deep/expensive scan profile
- per-API timing and call counts
- visible progress at region/API/subscanner level
- explicit free/paid/slow API plan before execution

## Root causes

1. Pack orchestration is serial.

   `run_all_scans` runs packs in `TOOL_ORDER` one by one. Each pack is wrapped in a `ThreadPoolExecutor(max_workers=1)`, which gives timeout isolation but no real parallelism.

2. Region scans are usually serial.

   Most packs do `for region in regions:` and make AWS API calls one region at a time. With 3 regions this is tolerable; with all enabled regions it multiplies latency.

3. Many packs recollect the same inventory.

   EC2 instances, VPCs, subnets, security groups, NAT gateways, load balancers, RDS instances, Lambda functions, CloudWatch alarms, log groups, S3 buckets, and CloudFormation stacks are queried independently by multiple packs.

4. Some default scans use deep or slow APIs.

   CloudFormation drift detection, IAM service-last-accessed jobs, exhaustive Service Quotas enumeration, CloudWatch metric lookups, Cost Explorer, and S3 per-bucket lookups are not cheap in latency. Some are also paid APIs.

5. Progress hides the slow operation.

   Users see a pack name for minutes, not the current service, region, API, item count, elapsed time, or whether a paid/slow API is being used.

6. Boto timeout/retry config is not consistently used.

   `BOTO_CONFIG` exists, but most pack code creates clients with `session.client(...)` without passing that config. Slow endpoint behavior is therefore inconsistent.

## Pack-by-pack audit

### cost

Primary cause: Cost Explorer API round trips and pagination, not local analysis.

Hot paths:

- `get_cost_by_dimension("service")`
- `get_anomalies_from_service`
- attribution calls for top anomalies
- reservation coverage/utilization and Savings Plans utilization
- optional rightsizing, purchase recommendation, marketplace, resource-level, tag, and network breakdown calls

Notes:

- Cost Explorer API is paid per request.
- Local pandas work is secondary.
- This pack needs a strict API budget and a local CUR/DuckDB path for cost investigations.

Fix direction:

- Make Cost Explorer a paid/online source, not the default fast path when local CUR exists.
- Add an API call budget and show expected CE request count.
- Prefer local CUR DuckDB for `investigate` and cost movement briefs.

### security

Primary cause: serial subscanners plus deep IAM polling.

Hot paths:

- scanner classes run sequentially: IAM, network, data, compute, logging, encryption
- IAM credential report has an explicit `sleep(2)`
- IAM service-last-accessed samples up to 10 roles and polls each job up to 8 times, one second per poll
- network/data/compute/logging scanners make many region-scoped calls serially

Worst offender:

- IAM service-last-accessed can add roughly 80 seconds in the default path before considering AWS latency.

Fix direction:

- Move service-last-accessed to `--deep`.
- Run security subscanners with bounded parallelism.
- Run regional inventory calls concurrently.

### sweep

Primary cause: serial compute/network/storage/database/monitoring scans and repeated regional inventory.

Hot paths:

- compute scans EBS volumes, EIPs, snapshots, AMIs, instances, ENIs
- network scans security groups, ENIs, NAT gateways, load balancers, target groups, target health, CloudWatch metrics
- storage scans global S3 buckets, then ECR repositories/images by region
- database scans snapshots and instances
- monitoring scans log groups, alarms, Lambda functions, and CloudWatch metrics

Fix direction:

- Split into fast inventory findings and deep metric findings.
- Reuse shared inventory for EC2, EBS, ENI, ELB, RDS, Lambda, logs, alarms.
- Make CloudWatch metric lookups opt-in or sampled.

### dr

Primary cause: six serial scanners and many bucket/database/backup lookups.

Hot paths:

- backup plans, vaults, recovery points, protected resources per region
- S3 list buckets, then versioning, replication, lifecycle per bucket
- RDS instances/clusters, DynamoDB tables and continuous backups, ElastiCache groups
- Route53 hosted zones, health checks, and record sets
- SPOF checks repeat EC2/NAT/instance inventory

Fix direction:

- Parallelize scanners and regions.
- Cache global S3 and Route53 data once.
- Cache regional EC2/RDS/DynamoDB inventory once.

### age

Primary cause: serial per-region lifecycle scan and per-resource detail calls.

Hot paths:

- Lambda functions per region
- RDS instances per region
- EC2 instances per region
- ACM list certificates, then `describe_certificate` per certificate
- EKS list clusters, then `describe_cluster` per cluster
- ElastiCache replication groups, then `describe_cache_clusters`

Fix direction:

- Parallelize by region.
- Batch where AWS supports it.
- Cap or parallelize per-certificate and per-cluster detail calls.

### drift

Primary cause: CloudFormation drift detection is inherently slow and currently default behavior.

Hot paths:

- list stacks per region
- trigger `detect_stack_drift` for each active stack
- poll `describe_stack_drift_detection_status` until complete or timeout
- describe resource drifts for drifted stacks
- coverage scan calls `list_stack_resources` per stack and recollects EC2/S3/Lambda/RDS inventory

Notes:

- This pack already parallelizes some stack-level operations, but it still blocks on AWS drift jobs.

Fix direction:

- Move actual drift detection to `--deep` or `kulshan drift detect`.
- Default to coverage/list-only quick scan.
- Cache stack resources and regional inventory.

### tag

Primary cause: Resource Groups Tagging API pagination plus S3 per-bucket tagging plus optional Cost Explorer.

Hot paths:

- `get_resources` per region
- global `list_buckets`
- `get_bucket_tagging` per bucket
- `get_tag_keys` samples regions
- non-quick mode calls Cost Explorer twice for tag cost impact

Fix direction:

- Parallelize region `get_resources`.
- Parallelize S3 bucket tag reads with a small bound.
- Make Cost Explorer tag impact opt-in unless the user accepts paid APIs.

### pulse

Primary cause: observability pack does many unrelated inventories serially.

Hot paths:

- logging: CloudTrail, S3 list buckets, per-bucket logging, VPCs, flow logs, CloudWatch log groups, RDS
- alarms: CloudWatch alarms plus EC2/RDS/ELB/Lambda/NAT/SNS inventory
- tracing: Config, ECS, EKS, Lambda, X-Ray per region

Likely user-visible symptom:

- The pack can sit on "Observability" for minutes because no substep progress is shown while per-bucket, per-region, and log-group pagination work runs.

Fix direction:

- Split logging, alarms, tracing into parallel subscans.
- Reuse inventory already collected by sweep/security/topo.
- Add live progress: current scanner, region, API, count.

### limit

Primary cause: exhaustive Service Quotas crawling.

Hot paths:

- for each region, `list_services`
- for every service, `list_service_quotas`
- for quotas with usage metrics, CloudWatch `get_metric_statistics`
- direct count enrichment repeats EC2, VPC, SG, ELB, IAM, RDS, CFN, EBS, S3 inventory

This is probably the single worst default pack for broad scans.

Fix direction:

- Default to critical quotas only.
- Move exhaustive Service Quotas enumeration to `--deep`.
- Avoid CloudWatch usage metrics by default.
- Reuse inventory counts instead of direct recounts.

### topo

Primary cause: serial EC2 network topology calls by region plus NAT CloudWatch metrics.

Hot paths:

- VPCs, subnets, IGWs, NAT gateways, peerings, TGWs, TGW attachments, VPNs, VPC endpoints, route tables, flow logs per region
- NAT gateway CloudWatch metric lookup per NAT gateway for transfer estimate

Fix direction:

- Parallelize by region.
- Reuse topology data with security, sweep, DR, and pulse.
- Make NAT metric lookup optional or defer it to cost investigation.

## What to fix first

### Phase 0: measure before changing behavior

Add a local scan profiler:

- pack elapsed time
- scanner/subscanner elapsed time
- AWS service and operation call count
- total AWS API wait time
- slowest operations
- paid/possibly-paid API calls

Output:

```text
kulshan report --packs all --profile lab --perf
```

Example:

```text
Slowest packs
1. limit   182s  742 API calls  service-quotas:list_service_quotas 613 calls
2. pulse    94s  318 API calls  logs:describe_log_groups 28 pages, s3:get_bucket_logging 92 calls
3. drift    80s  41 drift jobs  cloudformation:describe_stack_drift_detection_status 320 polls
```

### Phase 1: make default scan fast

Change defaults:

- `limit`: critical quotas only
- `drift`: coverage/list-only, no `detect_stack_drift`
- `security`: no IAM service-last-accessed jobs
- `topo`: no NAT CloudWatch metric lookups
- `sweep/pulse`: no CloudWatch metric-statistics calls
- `tag`: no Cost Explorer tag spend in default/free mode

Add `--deep` for the current expensive behavior.

### Phase 2: add bounded parallelism

Add:

- region-level executor with low default concurrency, for example 4
- subscanner executor for independent pack internals, for example 3
- shared boto config with `max_pool_connections` sized to concurrency
- adaptive retry mode

Do not blindly run all packs at once. Parallelism needs per-service limits and throttling awareness.

### Phase 3: build shared inventory

Collect once:

- EC2: instances, volumes, snapshots, ENIs, VPCs, subnets, security groups, route tables, flow logs, NAT gateways, EIPs
- ELB: load balancers, target groups, target health
- RDS: instances, clusters, snapshots
- Lambda: functions
- S3: buckets, optional bucket details
- CloudWatch: alarms, optional log groups
- CloudFormation: stacks, stack resources

Then packs consume inventory snapshots instead of calling AWS again.

### Phase 4: make the shell/operator UX honest

Add:

```text
show api-cost-plan
show scan-plan
run scan --fast
run scan --deep
show perf
show api-calls
```

During scans show:

```text
Observability > logging > s3:GetBucketLogging 38/92 buckets
Region: us-east-1
Elapsed: 41s
Paid APIs: none
```

## Engineering conclusion

Do not rewrite the scanner in assembly.

The fastest path is:

1. measure API time
2. remove deep APIs from default scans
3. parallelize bounded regional I/O
4. share inventory across packs
5. make local CUR/DuckDB the cost investigation path

Rust may become useful later for a compiled single binary, fast local parquet scans, or a high-performance local query engine wrapper. It will not fix the current scan latency until AWS API orchestration is fixed.
