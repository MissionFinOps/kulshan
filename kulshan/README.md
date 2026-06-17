# Kulshan

**Local-first AWS FinOps baseline. One command, one report.**

```bash
pip install kulshan
kulshan report
```

Kulshan reads your AWS Cost Explorer and produces a local FinOps baseline report. Where is the spend? What changed? What should you investigate next?

No SaaS. No CUR upload. No telemetry. No write access. Apache 2.0.

## Install

```bash
pip install kulshan        # macOS, Linux, Windows
```

Requires Python 3.9+. Works with the AWS credentials you already use.

## Quick Start

```bash
kulshan doctor              # Check what works with your current creds
kulshan report              # 90-day Cost Explorer baseline (default)
kulshan report -o report.html   # Save as HTML
kulshan report --packs cost,tag     # Add tag allocation
kulshan report --packs all --regions us-east-1   # Full diagnostic
```

## What You Get (Default)

The default `kulshan report` runs the Cost Explorer baseline:

- **Spend analysis** — 90-day lookback, anomaly detection (z-score, IQR, MAD)
- **Commitment health** — RI/SP coverage, utilization, on-demand exposure
- **Spend concentration** — which services dominate, diversification assessment
- **Spend trend** — daily average, direction, acceleration
- **Addressable savings** — what can be optimized and how much
- **Executive summary** — one paragraph for stakeholders

## Additional Packs (Opt-In)

Add inventory packs when you want deeper analysis:

```bash
kulshan report --packs security    # IAM, encryption, network posture
kulshan report --packs sweep       # Orphaned EBS, idle ALBs, waste
kulshan report --packs tag         # Tag compliance, cost attribution
kulshan report --packs all --regions us-east-1   # Everything
```

Output formats: terminal, JSON, HTML, SARIF, CSV.

## Trust & Security

- **Read-only** — 147 explicit audit actions, zero write actions
- **Local-first** — reports stay on your machine, no uploads
- **No telemetry** — no phone-home, no tracking
- **Published IAM policy** — inspect every action before granting access
- **Open source** — Apache 2.0, read every line on GitHub

## AWS API Costs

| Mode | AWS Cost |
|------|----------|
| Default (Cost Explorer baseline) | ~$0.20 (CE @ $0.01/request) |
| Security, sweep, DR, tag, etc. | $0 (free-tier APIs) |
| `kulshan report --packs all` | ~$0.20 (only cost pack charges) |

This is charged by AWS to your account, not by Kulshan.

## AI Agents

Kulshan works with Claude Code, Codex, Kiro, Cursor, and any agent that can run shell commands. See [`agent-pack/`](https://github.com/azz-kikkr/kulshan/tree/master/agent-pack) for integration docs.

## About the Name

Kulshan is the Lummi name for the mountain known colonially as Mt. Baker — meaning "great white watcher." We acknowledge the Lummi and Nooksack peoples as the original namers of this mountain.

## Built by

[Mission FinOps](https://missionfinops.com) — Mission, BC, Canada.

## License

Apache 2.0 — free and open source forever.
