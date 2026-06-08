"""Build resource relationship graph from scan data."""

import networkx as nx
from typing import Dict, Any, List


def build_graph(scan_resources: Dict[str, Any], account_id: str) -> nx.DiGraph:
    """Build a directed graph of AWS resource relationships."""
    G = nx.DiGraph()

    # Account node
    G.add_node(account_id, type="AWSAccount", label=f"Account {account_id}")

    # IAM Users
    for user in scan_resources.get("iam", {}).get("users", []):
        uid = user.get("Arn", user.get("UserName", ""))
        G.add_node(uid, type="IAMUser", label=user.get("UserName", ""), data=user)
        G.add_edge(account_id, uid, type="HAS_USER")
        for policy in user.get("AttachedManagedPolicies", []):
            G.add_node(policy["PolicyArn"], type="IAMPolicy", label=policy.get("PolicyName", ""))
            G.add_edge(uid, policy["PolicyArn"], type="HAS_POLICY")

    # IAM Roles
    for role in scan_resources.get("iam", {}).get("roles", []):
        rid = role.get("Arn", role.get("RoleName", ""))
        G.add_node(rid, type="IAMRole", label=role.get("RoleName", ""), data=role)
        G.add_edge(account_id, rid, type="HAS_ROLE")
        # Trust relationships
        trust = role.get("AssumeRolePolicyDocument", {})
        if isinstance(trust, str):
            import json
            trust = json.loads(trust)
        for stmt in trust.get("Statement", []):
            if stmt.get("Effect") != "Allow": continue
            principals = stmt.get("Principal", {})
            if isinstance(principals, str): principals = {"AWS": [principals]}
            for p in principals.get("AWS", []) if isinstance(principals.get("AWS", []), list) else [principals.get("AWS", "")]:
                if p and p != "*":
                    G.add_node(p, type="ExternalPrincipal" if account_id not in p else "IAMEntity", label=p.split("/")[-1])
                    G.add_edge(p, rid, type="CAN_ASSUME")

    # Security Groups and EC2
    for sg in scan_resources.get("network", {}).get("security_groups", []):
        sgid = sg["GroupId"]
        G.add_node(sgid, type="SecurityGroup", label=sg.get("GroupName", sgid), region=sg.get("_region", ""))
        for rule in sg.get("IpPermissions", []):
            for ip_range in rule.get("IpRanges", []):
                if ip_range.get("CidrIp") == "0.0.0.0/0":
                    G.add_node("INTERNET", type="Internet", label="Internet")
                    G.add_edge("INTERNET", sgid, type="EXPOSES_TO_INTERNET",
                              port_range=f"{rule.get('FromPort', 0)}-{rule.get('ToPort', 65535)}")

    # S3 Buckets
    for bucket in scan_resources.get("data", {}).get("s3_buckets", []):
        bname = bucket["Name"]
        G.add_node(f"s3://{bname}", type="S3Bucket", label=bname)
        G.add_edge(account_id, f"s3://{bname}", type="HAS_BUCKET")

    return G


def find_attack_paths(G: nx.DiGraph, max_paths: int = 5) -> List[Dict]:
    """Find the most critical attack paths in the graph."""
    paths = []

    # Find paths from Internet to sensitive resources
    if "INTERNET" in G:
        sensitive_types = {"S3Bucket", "IAMRole", "IAMUser"}
        for node in G.nodes():
            ntype = G.nodes[node].get("type", "")
            if ntype in sensitive_types:
                try:
                    for path in nx.all_simple_paths(G, "INTERNET", node, cutoff=6):
                        paths.append({
                            "source": "Internet",
                            "target": G.nodes[node].get("label", node),
                            "target_type": ntype,
                            "hops": len(path) - 1,
                            "path": [G.nodes[n].get("label", n) for n in path],
                            "edges": [G.edges[path[i], path[i+1]].get("type", "") for i in range(len(path)-1)],
                        })
                except nx.NetworkXNoPath:
                    pass

    # Sort by shortest path (most direct threat)
    paths.sort(key=lambda p: p["hops"])
    return paths[:max_paths]


def calculate_blast_radius(G: nx.DiGraph, start_node: str) -> Dict:
    """Calculate what a compromised node can reach."""
    reachable = set()
    traversal_edges = {"CAN_ASSUME", "HAS_POLICY", "CAN_ACCESS", "HAS_ROLE", "CAN_INVOKE"}

    queue = [start_node]
    visited = set()
    while queue:
        node = queue.pop(0)
        if node in visited: continue
        visited.add(node)
        reachable.add(node)
        for neighbor in G.successors(node):
            edge_type = G.edges[node, neighbor].get("type", "")
            if edge_type in traversal_edges:
                queue.append(neighbor)

    # Categorize reachable resources
    by_type = {}
    for node in reachable:
        ntype = G.nodes[node].get("type", "unknown")
        by_type.setdefault(ntype, []).append(G.nodes[node].get("label", node))

    return {"total_reachable": len(reachable), "by_type": by_type}
