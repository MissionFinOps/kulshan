# Audit Packs

Kulshan ships 10 audit packs. Each pack runs independently and produces a score (0–100) plus a list of typed findings. Packs can be run individually or in combination.

---

## Pack Summary

| Pack | Label | Weight | Description |
|------|-------|--------|-------------|
| `cost` | Cost Analyzer | 15% | Cost trends, anomalies, commitment gaps |
| `security` | Security Scanner | 15% | IAM, encryption, network exposure, logging |
| `sweep` | Waste Detector | 10% | Orphaned and idle resources |
| `dr` | DR Readiness | 12% | Backup coverage, multi-AZ, single points of failure |
| `age` | Lifecycle Audit | 8% | EOL runtimes, expiring certs, staleness |
| `drift` | IaC Drift | 10% | CloudFormation drift, IaC coverage |
| `tag` | Tag Governance | 8% | Tag compliance, unattributed spend |
| `pulse` | Observability | 8% | Alarm coverage, monitoring blind spots |
| `limit` | Quota Headroom | 6% | Service quota utilization, scaling risk |
| `topo` | Network Topology | 8% | VPC topology, CIDR overlaps, route integrity |

Weights determine contribution to the overall score when running multiple packs.

---

## Running Packs

```bash
# Default: cost only
kulshan report

# Specific packs
kulshan report --packs cost,security,sweep --regions us-east-1

# All packs
kulshan report --packs all --regions us-east-1,us-west-2
```

---

## Pack Details

### cost — Cost Analyzer

**What it detects:**
- Spending anomalies using statistical methods (z-score, IQR, MAD)
- Cross-reference against AWS Cost Anomaly Detection
- Month-over-month and week-over-week acceleration
- Commitment gaps (RI/SP coverage and utilization)
- Spend forecasting (trend extrapolation)
- Top-mover analysis by service, account, and usage type

**API dependency:** AWS Cost Explorer ($0.01/request, ~15 requests per run)

**Region scope:** Global (us-east-1 only)

**IAM actions required:**
- `ce:GetCostAndUsage`
- `ce:GetCostAndUsageWithResources`
- `ce:GetCostForecast`
- `ce:GetAnomalies`
- `ce:GetReservationCoverage`
- `ce:GetReservationUtilization`
- `ce:GetSavingsPlansUtilization`
- `ce:GetRightsizingRecommendation`
- `ce:GetTags`

**Finding kinds:** `anomaly_statistical`, `anomaly_aws`, `commitment_gap`, `spend_acceleration`, `forecast_breach`

---

### security — Security Scanner

**What it detects:**
- IAM misconfigurations (overly permissive policies, unused credentials, missing MFA)
- Encryption gaps (unencrypted volumes, buckets without default encryption)
- Network exposure (open security groups, public subnets, missing flow logs)
- Logging gaps (CloudTrail disabled, missing Config recorders)
- Public access (S3 public buckets, publicly accessible RDS)
- KMS key rotation status
- GuardDuty coverage

**API dependency:** Free AWS APIs

**Region scope:** Per-region (scans each selected region)

**IAM actions required:**
- `iam:*` (Get/List actions only)
- `ec2:DescribeSecurityGroups`, `ec2:DescribeFlowLogs`, `ec2:DescribeInstances`
- `s3:GetBucket*`, `s3:GetAccountPublicAccessBlock`
- `kms:DescribeKey`, `kms:GetKeyRotationStatus`, `kms:ListKeys`
- `cloudtrail:DescribeTrails`, `cloudtrail:GetTrailStatus`
- `config:DescribeConfigurationRecorders`
- `guardduty:ListDetectors`, `guardduty:GetDetector`
- `rds:DescribeDBInstances`

**Finding kinds:** `iam_admin_access`, `iam_unused_credentials`, `iam_no_mfa`, `sg_open_to_world`, `encryption_disabled`, `logging_gap`, `public_access`, `kms_rotation_disabled`

---

### sweep — Waste Detector

**What it detects:**
- Unattached EBS volumes
- Unused Elastic IPs
- Idle load balancers (no healthy targets)
- Stopped EC2 instances with attached volumes
- Orphaned snapshots
- Unused NAT gateways
- Empty ECR repositories
- Idle RDS instances (no connections)
- Detached network interfaces

**API dependency:** Free AWS APIs

**Region scope:** Per-region

**IAM actions required:**
- `ec2:DescribeVolumes`, `ec2:DescribeAddresses`, `ec2:DescribeInstances`
- `ec2:DescribeSnapshots`, `ec2:DescribeNatGateways`, `ec2:DescribeNetworkInterfaces`
- `elasticloadbalancing:DescribeLoadBalancers`, `elasticloadbalancing:DescribeTargetHealth`
- `rds:DescribeDBInstances`
- `ecr:DescribeRepositories`, `ecr:ListImages`
- `cloudwatch:GetMetricStatistics`

**Finding kinds:** `orphaned_volume`, `unused_eip`, `idle_lb`, `stopped_instance_with_storage`, `orphaned_snapshot`, `idle_nat_gw`, `empty_ecr`, `idle_rds`, `detached_eni`

---

### dr — DR Readiness

**What it detects:**
- Resources without backup plans
- Single-AZ deployments (RDS, ElastiCache, ECS)
- Single points of failure (single-instance ASGs, no multi-AZ)
- Missing cross-region replication
- RDS without automated backups
- S3 buckets without versioning
- DynamoDB without point-in-time recovery

**API dependency:** Free AWS APIs

**Region scope:** Per-region

**IAM actions required:**
- `backup:ListProtectedResources`, `backup:ListBackupPlans`, `backup:ListBackupVaults`
- `rds:DescribeDBInstances`, `rds:DescribeDBClusters`
- `ec2:DescribeInstances`, `ec2:DescribeAvailabilityZones`
- `autoscaling:DescribeAutoScalingGroups`
- `elasticache:DescribeCacheClusters`, `elasticache:DescribeReplicationGroups`
- `dynamodb:DescribeContinuousBackups`, `dynamodb:DescribeTable`
- `s3:GetBucketVersioning`, `s3:GetBucketReplication`

**Finding kinds:** `no_backup_plan`, `single_az`, `single_point_of_failure`, `no_cross_region_replication`, `no_pitr`, `no_versioning`

---

### age — Lifecycle Audit

**What it detects:**
- EOL Lambda runtimes (Python 3.8, Node.js 14, etc.)
- Expiring ACM certificates (within 30/60/90 days)
- Stale AMIs (unused, old)
- Outdated RDS engine versions
- Long-running EC2 instances without recent patching evidence
- Old ECS task definitions

**API dependency:** Free AWS APIs

**Region scope:** Per-region

**IAM actions required:**
- `lambda:ListFunctions`, `lambda:GetFunctionConfiguration`
- `acm:ListCertificates`, `acm:DescribeCertificate`
- `ec2:DescribeImages`, `ec2:DescribeInstances`
- `rds:DescribeDBInstances`, `rds:DescribeDBEngineVersions`
- `ecs:ListClusters`, `ecs:DescribeServices`

**Finding kinds:** `eol_runtime`, `expiring_certificate`, `stale_ami`, `outdated_engine`, `staleness_tax`

---

### drift — IaC Drift

**What it detects:**
- CloudFormation stack drift (actual vs. expected configuration)
- Resources not managed by any IaC stack
- Drift severity classification (property changes vs. resource deletion)
- IaC coverage percentage

**API dependency:** Free AWS APIs (CloudFormation drift detection may take time)

**Region scope:** Per-region

**IAM actions required:**
- `cloudformation:ListStacks`, `cloudformation:ListStackResources`
- `cloudformation:DetectStackDrift`, `cloudformation:DescribeStackDriftDetectionStatus`
- `cloudformation:DescribeStackResourceDrifts`

**Finding kinds:** `stack_drift_detected`, `resource_not_in_iac`, `drift_severity_high`

---

### tag — Tag Governance

**What it detects:**
- Resources missing required tags (configurable)
- Unattributed spend (cost not mappable to team/project/environment)
- Tag key inconsistencies (casing, typos)
- Tag coverage percentage by resource type

**API dependency:** Free AWS APIs + Cost Explorer for spend attribution

**Region scope:** Global (tag policies) + per-region (resource tags)

**IAM actions required:**
- `tag:GetResources`, `tag:GetTagKeys`, `tag:GetTagValues`
- `ce:GetCostAndUsage`, `ce:GetTags`

**Finding kinds:** `missing_required_tag`, `unattributed_spend`, `tag_inconsistency`, `low_tag_coverage`

---

### pulse — Observability

**What it detects:**
- Resources without CloudWatch alarms
- Missing metric filters on CloudWatch Logs
- Services without X-Ray tracing
- Alarm coverage gaps (CPU, memory, disk, error rates)
- Missing SNS notification targets

**API dependency:** Free AWS APIs

**Region scope:** Per-region

**IAM actions required:**
- `cloudwatch:DescribeAlarms`, `cloudwatch:ListMetrics`
- `logs:DescribeLogGroups`, `logs:DescribeMetricFilters`
- `xray:GetGroups`
- `sns:ListTopics`
- `lambda:ListFunctions`
- `rds:DescribeDBInstances`
- `ec2:DescribeInstances`

**Finding kinds:** `no_alarm`, `missing_metric_filter`, `no_tracing`, `alarm_coverage_gap`, `no_notification_target`

---

### limit — Quota Headroom

**What it detects:**
- Service quotas approaching limits (>80% utilization)
- Quotas already at limit
- Recently increased quotas (may indicate growth pressure)
- Scaling event risk assessment

**API dependency:** Free AWS APIs

**Region scope:** Per-region

**IAM actions required:**
- `servicequotas:ListServices`, `servicequotas:ListServiceQuotas`
- `servicequotas:GetServiceQuota`
- `servicequotas:ListRequestedServiceQuotaChangeHistory`
- `ec2:DescribeInstances`, `ec2:DescribeVpcs`, `ec2:DescribeSubnets`
- `lambda:GetAccountSettings`

**Finding kinds:** `quota_warning`, `quota_critical`, `quota_at_limit`, `scaling_risk`

---

### topo — Network Topology

**What it detects:**
- CIDR overlaps between VPCs
- Asymmetric or missing route table entries
- Transit gateway misconfigurations
- VPC peering without matching routes
- Subnet sizing issues
- Orphaned VPC endpoints
- Route integrity problems

**API dependency:** Free AWS APIs

**Region scope:** Per-region

**IAM actions required:**
- `ec2:DescribeVpcs`, `ec2:DescribeSubnets`, `ec2:DescribeRouteTables`
- `ec2:DescribeTransitGateways`, `ec2:DescribeTransitGatewayAttachments`
- `ec2:DescribeVpcPeeringConnections`, `ec2:DescribeVpcEndpoints`
- `ec2:DescribeVpnConnections`, `ec2:DescribeInternetGateways`
- `ec2:DescribeNatGateways`, `ec2:DescribeNetworkAcls`

**Finding kinds:** `cidr_overlap`, `asymmetric_route`, `tgw_misconfiguration`, `peering_without_route`, `subnet_sizing`, `orphaned_endpoint`, `route_integrity`

---

## Finding Schema

Every finding emitted by any pack follows the canonical v2.0 schema:

```json
{
  "id": "cost-anomaly_statistical-a1b2c3d4e5f67890",
  "pack": "cost",
  "kind": "anomaly_statistical",
  "fingerprint": "a1b2c3d4e5f67890",
  "title": "EC2 spend anomaly: +42% week-over-week",
  "severity": "high",
  "score_impact": -10,
  "estimated_monthly_impact": 1250.00,
  "confidence": 0.85,
  "effort": "medium",
  "risk": "safe",
  "account_id": "123456789012",
  "region": "us-east-1",
  "resource_arn": null,
  "resource_type": null,
  "service": "Amazon Elastic Compute Cloud",
  "description": "EC2 spend increased from $2,980 to $4,230...",
  "evidence": {},
  "recommended_action": "Review recent EC2 launches...",
  "compliance_frameworks": ["CIS 1.4"],
  "detected_at": "2026-07-15T10:30:00+00:00",
  "schema_version": "2.0"
}
```

### Key fields

| Field | Type | Description |
|-------|------|-------------|
| `id` | string | Deterministic ID: `{pack}-{kind}-{fingerprint}` |
| `fingerprint` | string | Stable hash — same finding across scans shares a fingerprint |
| `severity` | enum | `critical`, `high`, `medium`, `low`, `info` |
| `confidence` | float | 0.0–1.0 confidence in the finding |
| `effort` | enum | Remediation effort: `trivial`, `low`, `medium`, `high` |
| `risk` | enum | Remediation risk: `safe`, `low`, `medium`, `high` |
| `score_impact` | int | Impact on pack score: critical=-15, high=-10, medium=-5, low=-2, info=0 |
| `estimated_monthly_impact` | float | Dollar impact estimate (0 if not applicable) |

---

## Scoring Model

Each pack computes a score from 0 to 100. The overall score is a weighted average of all pack scores using the weights listed in the summary table above.

Score impact per severity:

| Severity | Score Impact |
|----------|-------------|
| critical | -15 |
| high | -10 |
| medium | -5 |
| low | -2 |
| info | 0 |

A pack with no findings scores 100. Each finding deducts points based on severity.

---

## Parallel Execution

All 10 packs are safe for parallel execution. When running multiple packs, Kulshan uses concurrent threads to scan regions in parallel within each pack. A full 10-pack scan completes significantly faster than sequential execution.

Estimated timing (single region):

| Pack | Approximate Duration |
|------|---------------------|
| cost | ~5s |
| security | ~25s |
| sweep | ~15s |
| dr | ~12s |
| age | ~8s |
| drift | ~5s |
| tag | ~4s |
| pulse | ~20s |
| limit | ~40s |
| topo | ~6s |

---

## Per-Pack IAM Policies

Minimal IAM policies for each pack are available at [`iam/per-check/`](../iam/per-check/):

```
iam/per-check/cost.json
iam/per-check/security.json
iam/per-check/sweep.json
iam/per-check/dr.json
iam/per-check/age.json
iam/per-check/drift.json
iam/per-check/tag.json
iam/per-check/pulse.json
iam/per-check/limit.json
iam/per-check/topo.json
```

Use these if you want to grant access for specific packs only. The full policy at [`iam/kulshan-readonly.json`](../iam/kulshan-readonly.json) covers all packs.
