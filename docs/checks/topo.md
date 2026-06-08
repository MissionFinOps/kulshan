# Topo (Network Topology / Architecture)

**Check pack:** `Kulshan.checks.topo`
**Orchestrator key:** `topo`
**Score weight:** 8% (see `TOOL_WEIGHTS` in `kulshan/src/kulshan/orchestrator.py`)
**IAM policy:** [`kulshan/iam/per-check/topo.json`](../../kulshan/iam/per-check/topo.json)

## What it does

Maps the entire VPC topology, scores network architecture quality 0-100, detects CIDR overlaps, generates SVG network diagrams, and identifies misconfigurations.

## What it maps

VPCs, subnets, route tables, Internet Gateways, NAT Gateways, VPC peering connections, Transit Gateways and attachments, VPN connections, VPC endpoints, NACLs, flow logs.

## Scoring breakdown (0-100): network architecture

| Category | Weight | What it checks |
|----------|--------|----------------|
| Architecture Quality | 25% | CIDR planning, multi-AZ subnets, no overlaps |
| Security Posture | 25% | Flow log coverage |
| Routing Integrity | 20% | Blackhole routes, VPN tunnel health |
| Redundancy | 15% | Multi-AZ NAT, multi-path routing |
| Observability | 15% | Flow logs, VPC endpoints |

## How to run

This pack runs as part of the unified Kulshan scan:

```bash
Kulshan Report                                   # all packs, all enabled regions
Kulshan Report --quick                           # 3 regions
Kulshan Report --format html -o report.html      # HTML output (with SVG diagram)
```

A per-pack-only CLI (`Kulshan scan topo`) is not exposed today.

## Permissions

Read-only. Key actions: `ec2:Describe*` (VPCs, subnets, route tables, NAT GWs, peering, TGW, VPN, endpoints, NACLs, flow logs). Granular per-pack policy at [`kulshan/iam/per-check/topo.json`](../../kulshan/iam/per-check/topo.json).

## Cost

$0.
