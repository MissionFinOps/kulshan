# Kulshan

Read-only AWS audit CLI.

```bash
pip install kulshan
kulshan report
```

One command. One report. Zero writes to your AWS account.

[![PyPI](https://img.shields.io/pypi/v/kulshan)](https://pypi.org/project/kulshan/)
[![License](https://img.shields.io/badge/license-Apache%202.0-blue)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.9%2B-blue)](https://python.org)

[Documentation](kulshan/docs/README.md) | [IAM Policy](kulshan/iam/kulshan-readonly.json) | [Changelog](kulshan/CHANGELOG.md)

---

## What Kulshan does

Ten read-only audit packs in one CLI. Cost anomalies, security posture, waste detection, DR gaps, drift, tag compliance, observability blind spots, quota headroom, and network topology - scored 0-100, exportable as HTML, JSON, SARIF, or CSV.

Reads your Cost Explorer data and your own CUR/Data Export Parquet files in place. No data leaves your machine. No SaaS account. No telemetry. No automatic outbound update requests.

---

## What Kulshan does not do

- Does not write to AWS. The IAM policy contains only Get, List, and Describe actions.
- Does not phone home. No telemetry or analytics. An optional PyPI update request is made only after you explicitly approve it.
- Does not require infrastructure. No databases, no containers, no SaaS.
- Does not hold credentials. Uses the same credential chain as the AWS CLI.

---

## Install

```bash
pip install kulshan
```

Python 3.9+. macOS, Linux, Windows. Optional extras: `kulshan[mcp]`, `kulshan[pdf]`, `kulshan[excel]`, `kulshan[pptx]`, or `kulshan[all]`.

### Consent-first update checks

When no update decision has been recorded in the previous nine hours, Kulshan shows the installed release date and age, then asks whether to check PyPI. The default is **No**. PyPI is contacted only after you answer **Yes**, before Kulshan reads AWS credentials or calls AWS.

```text
Kulshan 0.4.6: July 26, 2026 - released today.
Check PyPI for a newer version? [y/N]
```

Non-interactive and CI runs never prompt or contact PyPI. The request contains no AWS account, credential, profile, workspace, or report data. Kulshan never installs updates automatically.

---

## The 10 Audit Packs

| Pack | What it watches |
|------|-----------------|
| `cost` | Anomalies (z-score, IQR, MAD), commitment gaps, spend acceleration, forecasts |
| `security` | IAM, encryption, network exposure, logging, public access, GuardDuty |
| `sweep` | Orphaned volumes, unused EIPs, idle LBs, detached ENIs, empty repos |
| `dr` | Backup coverage, single-AZ, single points of failure, missing replication |
| `age` | EOL runtimes, expiring certs, stale AMIs, outdated engines |
| `drift` | CloudFormation drift, IaC coverage, severity classification |
| `tag` | Missing required tags, unattributed spend, key inconsistencies |
| `pulse` | Alarm gaps, missing metric filters, blind spots |
| `limit` | Quota headroom, at-limit services, scaling risk |
| `topo` | CIDR overlaps, route integrity, peering issues, TGW misconfigs |

```bash
kulshan report                                    # cost only (default, ~$0.15)
kulshan report --packs security,sweep             # specific packs (free APIs)
kulshan report --packs all --regions us-east-1    # full diagnostic
```

---

## Trust and Security

> Read-only by construction, not read-only by default. There is no cleanup mode to leave off, no write path to enable. The published IAM policy contains zero actions that create, modify, or delete AWS resources.

- 159 read-only actions, zero write actions. [Read every line.](kulshan/iam/kulshan-readonly.json)
- Reports stay on your machine
- No telemetry or analytics; optional PyPI checks require consent; either answer is remembered locally for nine hours
- Open source: Apache 2.0. IAM policy additionally CC BY 4.0.

---

## Quick Reference

```bash
kulshan preflight                       # Check credentials and permissions
kulshan report                          # Cost baseline (default)
kulshan report -o report.html           # HTML report
kulshan report --packs all --regions us-east-1 --deep  # Full deep scan
kulshan history                         # Past scans
kulshan workspace list                  # All environments
kulshan workspace reconcile             # Link shared-payer environments
kulshan shell                           # Interactive REPL
kulshan mcp-serve                       # MCP server for AI agents
```

---

## About the Name

Kulshan is the Lummi name for the mountain known colonially as Mt. Baker, meaning "great white watcher." The mountain is visible from Mission, BC and is an active volcano in the Cascade Range. We acknowledge the Lummi and Nooksack peoples as the original namers of this mountain.

---

## Maintained by

[Mission FinOps](https://missionfinops.com) - open-source AWS audit tooling.

---

## License

Apache 2.0. Free and open source forever.

## CUR / Data Export automation

Kulshan discovers modern AWS Data Exports and legacy CUR definitions through the selected payer profile or role. It ranks Parquet exports, remembers a workspace selection, uses the newest complete month by default, and can combine Cost Explorer with CUR top-mover detail.

```bash
kulshan cur discover
kulshan cur select EXPORT_NAME --cost-source hybrid
kulshan cur iam --export EXPORT_NAME       # prints policy; never applies it
kulshan report --cost-source hybrid --billing-period 2026-06
```

Unattended `auto` runs stay on Cost Explorer. Select `hybrid` or `cur` explicitly to permit unattended CUR reads.