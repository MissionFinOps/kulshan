"""Network Architecture Scoring Engine (0-100)."""
from typing import Dict

def calculate_score(scan_results: Dict) -> Dict:
    topo = scan_results.get("topology", {})
    findings = scan_results.get("findings", [])
    vpcs = topo.get("vpcs", [])
    subnets = topo.get("subnets", [])

    # Architecture Quality: 25%
    arch_score = 100.0
    cidr_overlaps = len([f for f in findings if "CIDR overlap" in f.get("title", "")])
    arch_score -= min(40, cidr_overlaps * 20)
    single_az = len([f for f in findings if "only 1 AZ" in f.get("title", "")])
    arch_score -= min(30, single_az * 10)
    default_vpcs = len([v for v in vpcs if v.get("is_default")])
    arch_score -= min(15, default_vpcs * 2)
    arch_score = max(0, arch_score)

    # Security Posture: 25%
    sec_score = 100.0
    flow_vpc_set = set(topo.get("flow_log_vpcs", []))
    total_vpcs = len(vpcs)
    if total_vpcs > 0:
        flow_pct = len(flow_vpc_set) / total_vpcs * 100
        sec_score = flow_pct
    sec_score = max(0, sec_score)

    # Routing Integrity: 20%
    route_score = 100.0
    total_bh = sum(rt.get("blackholes", 0) for rt in topo.get("route_tables", []))
    route_score -= min(50, total_bh * 15)
    vpn_down = len([v for v in topo.get("vpn_connections", []) if v["tunnels_up"] == 0 and v["state"] == "available"])
    route_score -= min(30, vpn_down * 15)
    route_score = max(0, route_score)

    # Redundancy: 15%
    red_score = 100.0
    # NAT GW redundancy per VPC
    vpc_nats = {}
    for nat in topo.get("nat_gws", []):
        vpc_nats.setdefault(nat["vpc_id"], []).append(nat)
    single_nat = sum(1 for nats in vpc_nats.values() if len(nats) == 1)
    red_score -= min(40, single_nat * 15)
    red_score = max(0, red_score)

    # Observability: 15%
    obs_score = 100.0
    if total_vpcs > 0:
        no_flow = total_vpcs - len(flow_vpc_set)
        obs_score -= min(60, (no_flow / total_vpcs) * 60)
    endpoints = len(topo.get("vpc_endpoints", []))
    if endpoints == 0 and total_vpcs > 0: obs_score -= 20
    obs_score = max(0, obs_score)

    overall = arch_score*0.25 + sec_score*0.25 + route_score*0.20 + red_score*0.15 + obs_score*0.15
    overall = max(0, min(100, overall))
    grade = _grade(overall)

    sev_counts = {"critical": 0, "high": 0, "medium": 0, "low": 0}
    for f in findings: sev_counts[f.get("severity", "medium")] = sev_counts.get(f.get("severity", "medium"), 0) + 1

    summary = {"vpcs": len(vpcs), "subnets": len(subnets), "igws": len(topo.get("igws", [])),
               "nat_gws": len(topo.get("nat_gws", [])), "peerings": len(topo.get("peerings", [])),
               "tgws": len(topo.get("tgws", [])), "vpn_connections": len(topo.get("vpn_connections", [])),
               "vpc_endpoints": endpoints, "route_tables": len(topo.get("route_tables", []))}

    return {"overall_score": round(overall, 1), "grade": grade,
            "total_findings": len(findings), "severity_counts": sev_counts,
            "breakdown": {
                "architecture": {"score": round(arch_score, 1), "weight": "25%", "label": "Architecture Quality"},
                "security": {"score": round(sec_score, 1), "weight": "25%", "label": "Security Posture"},
                "routing": {"score": round(route_score, 1), "weight": "20%", "label": "Routing Integrity"},
                "redundancy": {"score": round(red_score, 1), "weight": "15%", "label": "Redundancy"},
                "observability": {"score": round(obs_score, 1), "weight": "15%", "label": "Observability"},
            }, "summary": summary, "topology": topo, "findings": findings}

def _grade(score):
    if score >= 95: return "A+"
    if score >= 90: return "A"
    if score >= 85: return "A-"
    if score >= 80: return "B+"
    if score >= 75: return "B"
    if score >= 70: return "B-"
    if score >= 65: return "C+"
    if score >= 60: return "C"
    if score >= 55: return "C-"
    if score >= 45: return "D"
    return "F"

def grade_color(grade):
    if grade.startswith("A"): return "green"
    if grade.startswith("B"): return "yellow"
    if grade.startswith("C"): return "dark_orange"
    return "red"
