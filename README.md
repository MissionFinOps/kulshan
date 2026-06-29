# Kulshan 🏔️

**Local-first AWS FinOps baseline. One command, one report.**

```bash
pip install kulshan
kulshan report
```

Kulshan reads your AWS Cost Explorer and produces a local FinOps baseline report. Where is the spend? What changed? What should you investigate next?

No SaaS. No CUR upload. No telemetry. No write access. Apache 2.0.

[![PyPI](https://img.shields.io/pypi/v/kulshan)](https://pypi.org/project/kulshan/)
[![License](https://img.shields.io/badge/license-Apache%202.0-blue)](LICENSE.txt)
[![Python](https://img.shields.io/badge/python-3.9%2B-blue)](https://python.org)

---

## What You Get

```
$ kulshan report

  Kulshan FinOps Baseline · 90 days · account 1234****9012

  Cost Drivers:
    Amazon EC2          $14,200/mo  (+12% vs prior period)
    Amazon RDS           $4,800/mo  (stable)
    AWS Lambda           $1,200/mo  (+340% — anomaly detected)

  Savings Opportunities:
    RI/SP coverage: 62% (target: 80%)
    Rightsizing: 4 recommendations, est. $380/mo
    Unused commitments: $120/mo underutilized

  Top Actions:
    1. Investigate Lambda cost spike (+$900/mo, 3 methods agree)
    2. Increase Savings Plans coverage (gap: $2,100/mo on-demand)
    3. Rightsize 2 oversized RDS instances (est. $260/mo)

  Score: 78/100 [B]
  Report written to kulshan-report.html
```

---

## What It Answers

| Question | How |
|----------|-----|
| Where is spend going? | Service, account, region breakdown |
| What changed? | Period-over-period comparison, anomaly detection |
| What should I investigate? | Top actions ranked by estimated impact |
| Am I using commitments well? | RI/SP coverage and utilization |
| Is spend attributed? | Tag compliance, unattributed cost detection |
| What's the forecast? | Cost Explorer projection |

---

## Install

```bash
pip install kulshan       # from PyPI
pipx install kulshan      # isolated (recommended)
```

Requires: Python 3.9+ and AWS credentials.

---

## AWS Credentials

Kulshan uses the same credential chain as the AWS CLI. If `aws sts get-caller-identity` works, Kulshan works.

```bash
# Already configured? Just run it:
kulshan report

# SSO:
aws sso login --profile your-profile
kulshan --profile your-profile report

# Temporary credentials (from Console):
export AWS_ACCESS_KEY_ID=ASIA...
export AWS_SECRET_ACCESS_KEY=...
export AWS_SESSION_TOKEN=...
kulshan report

# Dedicated role:
kulshan --role-arn arn:aws:iam::123456789012:role/KulshanAudit report
```

---

## AWS API Cost

Kulshan's cost baseline reads AWS Cost Explorer APIs. AWS bills these at $0.01 per request.

| Mode | Expected cost | What happens |
|------|---------------|--------------|
| `kulshan report` (default) | ~$0.15–$0.25 | Cost Explorer queries only |
| `--packs cost,tag` | ~$0.15–$0.25 | Same CE queries + tag APIs (free) |
| `--packs sweep` | $0.00 | Regional EC2/EBS APIs (free tier) |
| `--packs all` | ~$0.15–$0.25 | CE + free regional APIs |

The CLI warns you before running Cost Explorer and asks for confirmation. Use `--yes` for CI/CD.

---

## Default vs. Optional Packs

**Default (runs with `kulshan report`):**

| Pack | What it answers |
|------|----------------|
| `cost` | Where is spend going? What changed? What anomalies exist? |

**FinOps add-ons (opt-in):**

| Pack | What it answers |
|------|----------------|
| `tag` | Is spend attributed? Who owns what? |
| `sweep` | What resources are idle or orphaned? (waste detection) |

**AWS diagnostics (opt-in, not FinOps-specific):**

| Pack | What it checks |
|------|---------------|
| `security` | IAM, encryption, network exposure |
| `dr` | Backup coverage, multi-AZ |
| `age` | EOL runtimes, expiring certs |
| `drift` | CloudFormation drift |
| `pulse` | Alarm coverage, logging gaps |
| `limit` | Service quota headroom |
| `topo` | VPC topology, CIDR overlaps |

```bash
# Default FinOps baseline
kulshan report

# Add tag allocation visibility
kulshan report --packs cost,tag

# Add waste detection
kulshan report --packs cost,tag,sweep --regions us-east-1

# Full diagnostic (all packs, explicit)
kulshan report --packs all --regions us-east-1
```


---

## S3 Readiness Check, Not S3 Analysis

Kulshan can check whether your AWS identity can see a CUR/Data Export layout in S3 before you copy files locally:

```bash
kulshan cur s3-check --s3 s3://bucket/prefix/
```

This command only lists up to 50 S3 objects and reads object metadata for one manifest and one Parquet file when found. It does not download CUR data, query Athena, use Glue, discover Data Exports, or run analysis. Local investigation still requires local Parquet files:

```bash
kulshan cur validate --path ./cur/
kulshan investigate ec2 --cur ./cur/ --month YYYY-MM
```

See `docs/iam-setup.md` for the optional read-only S3 policy.
## Experimental Local CUR/Data Export Investigations

Kulshan has an experimental local-only EC2 investigation path for customer-owned CUR/Data Export Parquet files. It is intended to reduce MTTE: Mean Time To Explanation.

Current support:

- Local `.parquet` file or local directory containing `.parquet` files.
- Terminal EC2 investigation brief.
- No AWS API calls from the investigation command.
- No `s3://` path support for analysis, AWS Data Export discovery, Glue, or Athena query support.

Local-only onboarding:

1. Export, download, or sync CUR/Data Export Parquet files to a local directory such as `./cur/`.
2. Validate the local files:
   ```bash
   kulshan cur validate --path ./cur/
   ```
3. Investigate EC2 movement for a billing month:
   ```bash
   kulshan investigate ec2 --cur ./cur/ --month YYYY-MM
   ```

Optional schema inspection:

```bash
kulshan cur schema --path ./cur/
```

IAM note:

Current local-only mode requires no AWS IAM permissions for the investigation command. S3 sync and future Athena/S3 discovery modes would require separate AWS permissions and are not implemented yet.

The EC2 investigation brief currently includes:

- Previous and current month EC2 cost
- Absolute and percentage delta
- Account contributors when account columns exist
- Region contributors when region/location columns exist
- Resource contributors when resource IDs exist
- Usage type contributors
- Tag and owner evidence from CUR tag columns
- Missing evidence when fields are absent
- Review questions for the finance/platform meeting

This is an early CUR MVP: local Parquet only, no S3 path support yet, and terminal output only. It is not a replacement for full CUR/Athena dashboards.

---

## Output Formats

```bash
kulshan report                          # Terminal
kulshan report -o report.html           # HTML (self-contained, shareable)
kulshan report --format json            # JSON (for agents, CI/CD)
kulshan report --format sarif           # SARIF (GitHub Security tab)
kulshan report --format csv             # CSV (spreadsheet)
```

---

## IAM Permissions

| Approach | What to attach |
|----------|---------------|
| **Quickest** | `ViewOnlyAccess` + `AWSBillingReadOnlyAccess` |
| **Minimal** | [`kulshan/iam/kulshan-readonly.json`](kulshan/iam/kulshan-readonly.json) (147 actions) |

The policy contains only `Get*`, `List*`, `Describe*` actions. Zero write actions. Published, auditable, version-controlled.

---

## Trust & Safety

| Guarantee | How to verify |
|-----------|--------------|
| No writes to AWS | [IAM policy](kulshan/iam/kulshan-readonly.json): audit actions only |
| Runs locally | No telemetry, no phone-home code |
| No data upload | Reports write to local files only |
| Open source | Apache 2.0 — read every line |
| Verifiable builds | GitHub Actions → PyPI trusted publishing |

---

## About the Name

Kulshan is the Lummi name for Mt. Baker. Before you climb a mountain, you look at the terrain. Before you change an AWS environment, you should understand it.

---

## Built by

Yuvdeep Singh / [Mission FinOps](https://missionfinops.com) — Mission, BC, Canada.

---

## Links

- **PyPI:** https://pypi.org/project/kulshan/
- **GitHub:** https://github.com/azz-kikkr/kulshan
- **Sample report:** https://missionfinops.com/sample/
- **IAM Policy:** [kulshan/iam/kulshan-readonly.json](kulshan/iam/kulshan-readonly.json)
