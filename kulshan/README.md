# Kulshan

**Generate a VP/CFO-ready AWS audit report in minutes.**

Local-first. Read-only. No CUR. No Athena. No SaaS.

```bash
pip install kulshan
aws sso login
kulshan report
```

## What is Kulshan?

Kulshan is a local-first AWS audit tool that generates a business-ready report from your AWS account.

Think of it as a blood test for your AWS bill.

One command. Ten audit packs. HTML and JSON output. No data leaves your machine.

## Install

```bash
pip install kulshan        # macOS, Linux, Windows
```

Requires Python 3.9+. Works with the AWS credentials you already use.

## Quick Start

```bash
pip install kulshan
aws sso login
kulshan report
```

Generates HTML and JSON reports locally using your existing AWS credentials.

## What You Get

The default `kulshan report` runs the Cost Explorer baseline:

- **Cost analysis:** multi-method anomaly detection (z-score, IQR, MAD), cross-referenced against AWS Cost Anomaly Detection
- **Commitment health:** RI/SP coverage, utilization, on-demand exposure
- **Spend concentration:** which services dominate, diversification assessment
- **Spend trend:** daily average, direction, acceleration
- **Addressable savings:** what can be optimized and how much
- **Executive summary:** one paragraph for stakeholders

### Additional Packs (Opt-In)

- **Security posture:** 50+ checks across IAM, encryption, network exposure, logging, public access
- **Waste detection:** orphaned EBS volumes, idle ALBs, unused EIPs, NAT gateway waste
- **DR readiness:** backup coverage, multi-AZ deployment, single points of failure
- **Lifecycle audit:** EOL runtimes, expiring certificates, staleness tax
- **IaC drift:** CloudFormation drift detection, IaC coverage gaps
- **Tag compliance:** tag governance, unattributed spend, dark money
- **Observability:** alarm coverage, logging gaps, blind-spot heatmap
- **Quota headroom:** service limits, scaling event planner
- **Network topology:** VPC mapping, CIDR overlaps, route integrity

Output formats: terminal, JSON, HTML, SARIF, CSV.

## More Commands

```bash
kulshan doctor                          # Verify credentials and permissions
kulshan report --quick                  # Fast scan (3 regions, ~60s)
kulshan report -o report.html           # Save as HTML
kulshan report --packs security,sweep   # Run specific packs
kulshan report --packs all              # Full 10-pack diagnostic
kulshan shell                           # Interactive REPL
```

## Trust & Security

- **Read-only:** 147 explicit audit actions, zero write actions
- **Local-first:** reports stay on your machine, no uploads
- **No telemetry:** no phone-home, no tracking
- **Published IAM policy:** inspect every action before granting access
- **Open source:** Apache 2.0, read every line on GitHub

## AWS API Costs

| Mode | AWS Cost |
|------|----------|
| Default (Cost Explorer baseline) | ~$0.20 (CE @ $0.01/request) |
| Security, sweep, DR, tag, etc. | $0 (free-tier APIs) |
| `kulshan report --packs all` | ~$0.20 (only cost pack charges) |

This is charged by AWS to your account, not by Kulshan.

## About the Name

Kulshan is the Lummi name for the mountain known colonially as Mt. Baker, meaning "great white watcher." We acknowledge the Lummi and Nooksack peoples as the original namers of this mountain.

## Built by

[Mission FinOps](https://missionfinops.com) | Mission, BC, Canada.

## AI Agents

Kulshan works with Claude Code, Codex, Kiro, Cursor, and any agent that can run shell commands. See [`agents/`](https://github.com/azz-kikkr/kulshan/tree/master/agents) for integration docs.

## License

Apache 2.0. Free and open source forever.
