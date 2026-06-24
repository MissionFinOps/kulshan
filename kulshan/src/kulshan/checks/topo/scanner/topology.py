"""Discover full network topology: VPCs, subnets, gateways, peering, TGW."""

import ipaddress
from typing import Dict, List, Tuple
from ..utils.aws import safe_api_call, paginate_all


def scan_topology(session, regions, progress=None, task_id=None, estimate_transfer=False) -> Tuple[Dict, List[str]]:
    findings = []
    errors = []
    topo = {"vpcs": [], "subnets": [], "igws": [], "nat_gws": [], "peerings": [],
            "tgws": [], "tgw_attachments": [], "vpn_connections": [],
            "vpc_endpoints": [], "route_tables": [], "flow_log_vpcs": set()}

    for region in regions:
        ec2 = session.client("ec2", region_name=region)

        # VPCs
        resp, err = safe_api_call(ec2, "describe_vpcs")
        if err: errors.append(f"VPCs ({region}): {err}")
        else:
            for vpc in (resp or {}).get("Vpcs", []):
                name = _get_name(vpc.get("Tags", []))
                topo["vpcs"].append({"id": vpc["VpcId"], "cidr": vpc.get("CidrBlock", "?"),
                                     "name": name, "region": region, "is_default": vpc.get("IsDefault", False),
                                     "state": vpc.get("State", "?")})

        # Subnets
        resp, _ = safe_api_call(ec2, "describe_subnets")
        for sub in (resp or {}).get("Subnets", []):
            topo["subnets"].append({"id": sub["SubnetId"], "vpc_id": sub["VpcId"],
                                    "cidr": sub.get("CidrBlock", "?"), "az": sub.get("AvailabilityZone", "?"),
                                    "name": _get_name(sub.get("Tags", [])), "region": region,
                                    "public_ip": sub.get("MapPublicIpOnLaunch", False)})

        # Internet Gateways
        resp, _ = safe_api_call(ec2, "describe_internet_gateways")
        for igw in (resp or {}).get("InternetGateways", []):
            vpc_ids = [a["VpcId"] for a in igw.get("Attachments", []) if a.get("State") == "attached"]
            topo["igws"].append({"id": igw["InternetGatewayId"], "vpc_ids": vpc_ids, "region": region})

        # NAT Gateways
        resp, _ = safe_api_call(ec2, "describe_nat_gateways", Filters=[{"Name": "state", "Values": ["available"]}])
        for nat in (resp or {}).get("NatGateways", []):
            topo["nat_gws"].append({"id": nat["NatGatewayId"], "vpc_id": nat.get("VpcId", "?"),
                                    "subnet_id": nat.get("SubnetId", "?"), "region": region})

        # VPC Peering
        resp, _ = safe_api_call(ec2, "describe_vpc_peering_connections",
                                 Filters=[{"Name": "status-code", "Values": ["active"]}])
        for peer in (resp or {}).get("VpcPeeringConnections", []):
            req = peer.get("RequesterVpcInfo", {}); acc = peer.get("AccepterVpcInfo", {})
            topo["peerings"].append({"id": peer["VpcPeeringConnectionId"],
                                     "requester_vpc": req.get("VpcId", "?"), "requester_cidr": req.get("CidrBlock", "?"),
                                     "accepter_vpc": acc.get("VpcId", "?"), "accepter_cidr": acc.get("CidrBlock", "?"),
                                     "region": region})

        # Transit Gateways
        try:
            resp, _ = safe_api_call(ec2, "describe_transit_gateways")
            for tgw in (resp or {}).get("TransitGateways", []):
                if tgw.get("State") == "available":
                    topo["tgws"].append({"id": tgw["TransitGatewayId"], "region": region,
                                         "name": _get_name(tgw.get("Tags", []))})
            # TGW Attachments
            resp, _ = safe_api_call(ec2, "describe_transit_gateway_attachments")
            for att in (resp or {}).get("TransitGatewayAttachments", []):
                topo["tgw_attachments"].append({"id": att.get("TransitGatewayAttachmentId", "?"),
                                                 "tgw_id": att.get("TransitGatewayId", "?"),
                                                 "resource_type": att.get("ResourceType", "?"),
                                                 "resource_id": att.get("ResourceId", "?"),
                                                 "state": att.get("State", "?"), "region": region})
        except Exception: pass

        # VPN Connections
        try:
            resp, _ = safe_api_call(ec2, "describe_vpn_connections")
            for vpn in (resp or {}).get("VpnConnections", []):
                tunnels_up = sum(1 for t in vpn.get("VgwTelemetry", []) if t.get("Status") == "UP")
                tunnels_total = len(vpn.get("VgwTelemetry", []))
                topo["vpn_connections"].append({"id": vpn["VpnConnectionId"], "state": vpn.get("State", "?"),
                                                 "tunnels_up": tunnels_up, "tunnels_total": tunnels_total,
                                                 "region": region})
        except Exception: pass

        # VPC Endpoints
        resp, _ = safe_api_call(ec2, "describe_vpc_endpoints")
        for ep in (resp or {}).get("VpcEndpoints", []):
            topo["vpc_endpoints"].append({"id": ep["VpcEndpointId"], "vpc_id": ep.get("VpcId", "?"),
                                          "service": ep.get("ServiceName", "?"),
                                          "type": ep.get("VpcEndpointType", "?"), "region": region})

        # Route Tables
        resp, _ = safe_api_call(ec2, "describe_route_tables")
        for rt in (resp or {}).get("RouteTables", []):
            blackholes = sum(1 for r in rt.get("Routes", []) if r.get("State") == "blackhole")
            has_igw = any(r.get("GatewayId", "").startswith("igw-") for r in rt.get("Routes", []))
            topo["route_tables"].append({"id": rt["RouteTableId"], "vpc_id": rt.get("VpcId", "?"),
                                          "blackholes": blackholes, "has_igw_route": has_igw,
                                          "route_count": len(rt.get("Routes", [])), "region": region})

        # Flow Logs
        resp, _ = safe_api_call(ec2, "describe_flow_logs")
        for fl in (resp or {}).get("FlowLogs", []):
            rid = fl.get("ResourceId", "")
            if rid.startswith("vpc-"): topo["flow_log_vpcs"].add(rid)

        if progress and task_id:
            progress.advance(task_id)

    # Data transfer cost estimation uses CloudWatch metrics and is reserved for deep scans.
    if estimate_transfer:
        _estimate_transfer_costs(session, topo, errors)
    else:
        topo["transfer_costs"] = {"total_monthly": 0, "skipped": "Run with --deep to estimate transfer costs from CloudWatch metrics."}

    # CIDR overlap detection
    _detect_cidr_overlaps(topo, findings)

    # Architecture findings
    _analyze_architecture(topo, findings)

    topo["flow_log_vpcs"] = list(topo["flow_log_vpcs"])
    return {"topology": topo, "findings": findings}, errors


def _get_name(tags):
    for t in tags:
        if t.get("Key") == "Name": return t.get("Value", "")
    return ""


def _detect_cidr_overlaps(topo, findings):
    vpcs = topo["vpcs"]
    overlaps = []
    for i, v1 in enumerate(vpcs):
        for v2 in vpcs[i+1:]:
            try:
                net1 = ipaddress.ip_network(v1["cidr"], strict=False)
                net2 = ipaddress.ip_network(v2["cidr"], strict=False)
                if net1.overlaps(net2):
                    overlaps.append((v1, v2))
            except Exception:
                pass
    if overlaps:
        for v1, v2 in overlaps:
            findings.append({"category": "architecture", "severity": "high",
                             "title": f"CIDR overlap: {v1['name'] or v1['id']} ({v1['cidr']}) ↔ {v2['name'] or v2['id']} ({v2['cidr']})",
                             "detail": "Overlapping CIDRs prevent VPC peering and cause routing conflicts.",
                             "recommendation": "Re-IP one of the VPCs or use NAT for connectivity."})


def _analyze_architecture(topo, findings):
    # VPCs without subnets in multiple AZs
    vpc_azs = {}
    for sub in topo["subnets"]:
        vpc_id = sub["vpc_id"]
        if vpc_id not in vpc_azs: vpc_azs[vpc_id] = set()
        vpc_azs[vpc_id].add(sub["az"])
    for vpc in topo["vpcs"]:
        if vpc["is_default"]: continue
        azs = vpc_azs.get(vpc["id"], set())
        if len(azs) == 1:
            findings.append({"category": "architecture", "severity": "medium",
                             "title": f"VPC '{vpc['name'] or vpc['id']}' has subnets in only 1 AZ",
                             "detail": "No multi-AZ redundancy.", "recommendation": "Add subnets in additional AZs."})

    # Blackhole routes
    total_bh = sum(rt["blackholes"] for rt in topo["route_tables"])
    if total_bh > 0:
        findings.append({"category": "routing", "severity": "medium",
                         "title": f"{total_bh} blackhole route(s) detected",
                         "detail": "Routes pointing to deleted resources.", "recommendation": "Clean up stale routes."})

    # VPN tunnels down
    for vpn in topo["vpn_connections"]:
        if vpn["state"] == "available" and vpn["tunnels_up"] == 0:
            findings.append({"category": "connectivity", "severity": "high",
                             "title": f"VPN {vpn['id']} has all tunnels DOWN",
                             "detail": f"0/{vpn['tunnels_total']} tunnels up.", "recommendation": "Investigate VPN connectivity."})

    # Flow log coverage
    vpc_ids = {v["id"] for v in topo["vpcs"]}
    no_flow = vpc_ids - set(topo.get("flow_log_vpcs", []))
    if no_flow:
        findings.append({"category": "observability", "severity": "high",
                         "title": f"{len(no_flow)}/{len(vpc_ids)} VPCs have no flow logs",
                         "detail": "Network traffic is invisible.", "recommendation": "Enable VPC Flow Logs."})


# ─── Data Transfer Cost Estimation ────────────────────────────────────────────

# AWS data transfer pricing (USD per GB, approximate)
TRANSFER_RATES = {
    "nat_gw_per_gb": 0.045,          # NAT Gateway processing
    "nat_gw_hourly": 0.045,          # NAT Gateway hourly ($32.40/mo)
    "cross_az_per_gb": 0.01,         # Cross-AZ (each direction)
    "peering_same_region_per_gb": 0.01,  # VPC peering same region
    "peering_cross_region_per_gb": 0.02, # VPC peering cross region
    "tgw_per_gb": 0.02,              # Transit Gateway processing
    "tgw_attachment_hourly": 0.05,   # TGW attachment ($36/mo)
    "vpn_hourly": 0.05,             # VPN connection ($36/mo)
    "vpc_endpoint_hourly": 0.01,     # Interface endpoint ($7.20/mo)
}


def _estimate_transfer_costs(session, topo, errors):
    """Estimate monthly data transfer costs for network components.

    Uses CloudWatch metrics for NAT GW bytes where available,
    falls back to fixed hourly costs for other components.
    """
    costs = {
        "nat_gws": [],
        "peerings": [],
        "tgw_attachments": [],
        "vpn_connections": [],
        "vpc_endpoints": [],
        "total_monthly": 0,
    }

    # NAT Gateway costs, try CloudWatch for actual bytes processed
    for nat in topo.get("nat_gws", []):
        nat_cost = {"id": nat["id"], "vpc_id": nat["vpc_id"], "region": nat["region"]}
        gb_processed = _get_nat_gw_bytes(session, nat["id"], nat["region"])
        if gb_processed is not None:
            processing_cost = gb_processed * TRANSFER_RATES["nat_gw_per_gb"]
            hourly_cost = TRANSFER_RATES["nat_gw_hourly"] * 730  # ~730 hrs/mo
            nat_cost["gb_processed_monthly"] = round(gb_processed, 1)
            nat_cost["processing_cost"] = round(processing_cost, 2)
            nat_cost["hourly_cost"] = round(hourly_cost, 2)
            nat_cost["total_monthly"] = round(processing_cost + hourly_cost, 2)
        else:
            # Fallback: just hourly cost
            hourly_cost = TRANSFER_RATES["nat_gw_hourly"] * 730
            nat_cost["gb_processed_monthly"] = None
            nat_cost["processing_cost"] = None
            nat_cost["hourly_cost"] = round(hourly_cost, 2)
            nat_cost["total_monthly"] = round(hourly_cost, 2)
        costs["nat_gws"].append(nat_cost)

    # Peering costs, estimate based on same-region vs cross-region
    vpc_regions = {v["id"]: v["region"] for v in topo.get("vpcs", [])}
    for peer in topo.get("peerings", []):
        req_region = vpc_regions.get(peer["requester_vpc"], "?")
        acc_region = vpc_regions.get(peer["accepter_vpc"], "?")
        cross_region = req_region != acc_region and req_region != "?" and acc_region != "?"
        rate = TRANSFER_RATES["peering_cross_region_per_gb"] if cross_region else TRANSFER_RATES["peering_same_region_per_gb"]
        costs["peerings"].append({
            "id": peer["id"],
            "cross_region": cross_region,
            "rate_per_gb": rate,
            "note": f"${rate}/GB ({'cross-region' if cross_region else 'same-region'})",
        })

    # TGW attachment costs, fixed hourly per attachment
    for att in topo.get("tgw_attachments", []):
        if att.get("state") == "available":
            monthly = TRANSFER_RATES["tgw_attachment_hourly"] * 730
            costs["tgw_attachments"].append({
                "id": att["id"],
                "resource_id": att["resource_id"],
                "hourly_cost": TRANSFER_RATES["tgw_attachment_hourly"],
                "total_monthly": round(monthly, 2),
                "processing_rate": TRANSFER_RATES["tgw_per_gb"],
            })

    # VPN costs, fixed hourly
    for vpn in topo.get("vpn_connections", []):
        if vpn["state"] == "available":
            monthly = TRANSFER_RATES["vpn_hourly"] * 730
            costs["vpn_connections"].append({
                "id": vpn["id"],
                "total_monthly": round(monthly, 2),
            })

    # Interface VPC endpoint costs
    for ep in topo.get("vpc_endpoints", []):
        if ep.get("type") == "Interface":
            monthly = TRANSFER_RATES["vpc_endpoint_hourly"] * 730
            costs["vpc_endpoints"].append({
                "id": ep["id"],
                "service": ep["service"],
                "total_monthly": round(monthly, 2),
            })

    # Total
    costs["total_monthly"] = round(
        sum(n["total_monthly"] for n in costs["nat_gws"]) +
        sum(a["total_monthly"] for a in costs["tgw_attachments"]) +
        sum(v["total_monthly"] for v in costs["vpn_connections"]) +
        sum(e["total_monthly"] for e in costs["vpc_endpoints"]),
        2
    )

    topo["transfer_costs"] = costs


def _get_nat_gw_bytes(session, nat_gw_id, region):
    """Get NAT Gateway bytes processed in the last 30 days from CloudWatch."""
    try:
        from datetime import datetime, timezone, timedelta
        cw = session.client("cloudwatch", region_name=region)
        end = datetime.now(timezone.utc)
        start = end - timedelta(days=30)
        resp = cw.get_metric_statistics(
            Namespace="AWS/NATGateway",
            MetricName="BytesOutToDestination",
            Dimensions=[{"Name": "NatGatewayId", "Value": nat_gw_id}],
            StartTime=start, EndTime=end,
            Period=86400 * 30,  # 30-day sum
            Statistics=["Sum"],
        )
        datapoints = resp.get("Datapoints", [])
        if datapoints:
            total_bytes = sum(dp.get("Sum", 0) for dp in datapoints)
            return total_bytes / (1024 ** 3)  # Convert to GB
    except Exception:
        pass
    return None


def filter_topology_by_vpc(topo, vpc_filter):
    """Filter topology data to a single VPC (by ID or name substring).

    Returns a new topology dict containing only resources related to the matched VPC(s).
    """
    # Find matching VPCs
    matched_vpc_ids = set()
    for vpc in topo.get("vpcs", []):
        if vpc_filter.lower() in (vpc["id"].lower()):
            matched_vpc_ids.add(vpc["id"])
        elif vpc.get("name") and vpc_filter.lower() in vpc["name"].lower():
            matched_vpc_ids.add(vpc["id"])

    if not matched_vpc_ids:
        return topo  # No match, return everything

    filtered = {
        "vpcs": [v for v in topo["vpcs"] if v["id"] in matched_vpc_ids],
        "subnets": [s for s in topo["subnets"] if s["vpc_id"] in matched_vpc_ids],
        "igws": [i for i in topo["igws"] if any(vid in matched_vpc_ids for vid in i.get("vpc_ids", []))],
        "nat_gws": [n for n in topo["nat_gws"] if n["vpc_id"] in matched_vpc_ids],
        "peerings": [p for p in topo["peerings"]
                     if p["requester_vpc"] in matched_vpc_ids or p["accepter_vpc"] in matched_vpc_ids],
        "tgws": topo.get("tgws", []),  # Keep TGWs if any attachment matches
        "tgw_attachments": [a for a in topo.get("tgw_attachments", [])
                            if a.get("resource_id") in matched_vpc_ids],
        "vpn_connections": topo.get("vpn_connections", []),
        "vpc_endpoints": [e for e in topo.get("vpc_endpoints", []) if e["vpc_id"] in matched_vpc_ids],
        "route_tables": [r for r in topo.get("route_tables", []) if r["vpc_id"] in matched_vpc_ids],
        "flow_log_vpcs": [v for v in topo.get("flow_log_vpcs", []) if v in matched_vpc_ids],
        "transfer_costs": topo.get("transfer_costs", {}),
    }

    # Filter transfer costs too
    tc = topo.get("transfer_costs", {})
    if tc:
        filtered["transfer_costs"] = {
            "nat_gws": [n for n in tc.get("nat_gws", []) if n["vpc_id"] in matched_vpc_ids],
            "peerings": tc.get("peerings", []),  # Keep all peerings that touch this VPC
            "tgw_attachments": [a for a in tc.get("tgw_attachments", [])
                                if a.get("resource_id") in matched_vpc_ids],
            "vpn_connections": tc.get("vpn_connections", []),
            "vpc_endpoints": [e for e in tc.get("vpc_endpoints", [])
                              if any(ep["vpc_id"] in matched_vpc_ids
                                     for ep in topo.get("vpc_endpoints", [])
                                     if ep["id"] == e["id"])],
            "total_monthly": 0,
        }
        fc = filtered["transfer_costs"]
        fc["total_monthly"] = round(
            sum(n["total_monthly"] for n in fc["nat_gws"]) +
            sum(a["total_monthly"] for a in fc["tgw_attachments"]) +
            sum(v["total_monthly"] for v in fc["vpn_connections"]) +
            sum(e["total_monthly"] for e in fc["vpc_endpoints"]),
            2
        )

    return filtered
