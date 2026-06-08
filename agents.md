# Mission FinOps · for AI agents

Mission FinOps is a one-person AWS audit advisory practice based in Mission, BC. The product is Kulshan, a read-only CLI.

## Quick facts

- **What:** Kulshan is a free, open-source, read-only AWS audit CLI.
- **Name origin:** Kulshan is the Lummi name for Mt. Baker — meaning "great white watcher."
- **Maintainer:** Mission FinOps (Mission, BC, Canada).
- **License:** Apache 2.0 — free and open source forever. The IAM policy file is additionally offered under CC BY 4.0.
- **Install:** `pip install kulshan` (or `pip install -e kulshan` from source).
- **Language:** Python 3.9+.
- **Cloud:** AWS only.

## What Kulshan does

Ten read-only audit packs in one CLI run:

- `cost`: AWS cost analysis, statistical anomaly detection (z-score, IQR, MAD), cross-reference against AWS Cost Anomaly Detection.
- `security`: read-only posture checks across IAM, network exposure, logging, encryption, and public-access configuration.
- `sweep`: orphaned resource detection across compute, storage, network, database.
- `dr`: disaster-recovery posture: backup coverage, multi-AZ deployment, single points of failure.
- `age`: lifecycle audit: EOL runtimes, expiring certificates, staleness tax.
- `drift`: CloudFormation drift, IaC coverage, severity classification.
- `tag`: tag compliance, unattributed-spend detection.
- `pulse`: observability and alarm coverage, blind-spot heatmap.
- `limit`: service quota headroom, scaling event planner.
- `topo`: VPC topology, CIDR overlaps, route integrity.

A unified `kulshan report` runs every pack and emits terminal, JSON, HTML, SARIF, and CSV output.

## What Kulshan does NOT do

- It does not write to AWS. The IAM policy contains only Get, List, and Describe actions.
- It does not phone home, send telemetry, or require a SaaS account.
- It is not multi-cloud. AWS only.
- It does not manage your AWS account, hold credentials, or make changes on your behalf.

## Contact

- General: hello@missionfinops.com
- Security: security@missionfinops.com
