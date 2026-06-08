"""Crown Jewels Mode, inside-out security analysis starting from what matters most."""

from typing import Dict, List, Any
import networkx as nx
from .scanner.base import Finding, Severity


def analyze_crown_jewels(graph: nx.DiGraph, jewel_arns: List[str],
                         findings: List[Finding]) -> List[Dict]:
    """Analyze defense posture for specified crown jewel resources."""
    results = []

    for arn in jewel_arns:
        # Find the node in graph (try exact match, then partial)
        target_node = None
        for node in graph.nodes():
            if node == arn or arn in str(node):
                target_node = node
                break

        if not target_node:
            results.append({
                "arn": arn, "found": False,
                "message": f"Resource not found in scan data. Ensure it exists in a scanned region."
            })
            continue

        # Reverse BFS: who can reach this resource?
        predecessors = set()
        queue = [target_node]
        visited = set()
        paths_to_jewel = []

        while queue:
            node = queue.pop(0)
            if node in visited:
                continue
            visited.add(node)
            predecessors.add(node)
            for pred in graph.predecessors(node):
                if pred not in visited:
                    queue.append(pred)

        # Find paths from internet
        internet_paths = []
        if "INTERNET" in graph and target_node in graph:
            try:
                for path in nx.all_simple_paths(graph, "INTERNET", target_node, cutoff=8):
                    internet_paths.append({
                        "path": [graph.nodes[n].get("label", n) for n in path],
                        "hops": len(path) - 1,
                    })
            except (nx.NetworkXNoPath, nx.NodeNotFound):
                pass

        # Count identities with access
        identity_types = {"IAMUser", "IAMRole", "ExternalPrincipal"}
        identities = [n for n in predecessors if graph.nodes.get(n, {}).get("type") in identity_types]
        human_identities = [n for n in identities if graph.nodes.get(n, {}).get("type") == "IAMUser"]
        service_identities = [n for n in identities if graph.nodes.get(n, {}).get("type") == "IAMRole"]
        external_identities = [n for n in identities if graph.nodes.get(n, {}).get("type") == "ExternalPrincipal"]

        # Defense layers (count security controls protecting this resource)
        defense_layers = []
        node_data = graph.nodes.get(target_node, {})
        node_type = node_data.get("type", "")

        # Check if encrypted
        for pred in graph.predecessors(target_node):
            if graph.edges[pred, target_node].get("type") == "ENCRYPTED_BY":
                defense_layers.append("Encryption (KMS)")

        # Check related findings
        related_findings = []
        resource_id = node_data.get("label", target_node)
        for f in findings:
            if resource_id in f.resource_id or resource_id in f.resource_arn or resource_id in f.title:
                related_findings.append(f)

        # Defense score (100 = well defended, 0 = exposed)
        defense_score = 100
        for f in related_findings:
            if f.severity == Severity.CRITICAL:
                defense_score -= 25
            elif f.severity == Severity.HIGH:
                defense_score -= 15
            elif f.severity == Severity.MEDIUM:
                defense_score -= 5
        if internet_paths:
            defense_score -= 20
        if external_identities:
            defense_score -= 10
        defense_score = max(0, min(100, defense_score))

        # Recommendations
        recommendations = []
        if internet_paths:
            shortest = min(internet_paths, key=lambda p: p["hops"])
            recommendations.append(f"Sever internet path ({shortest['hops']} hops): review security groups and IAM roles in the chain")
        if external_identities:
            recommendations.append(f"Review {len(external_identities)} external identity/ies with access to this resource")
        for f in related_findings:
            if f.severity in (Severity.CRITICAL, Severity.HIGH):
                recommendations.append(f"Fix: {f.title} ({f.remediation})")
        if not defense_layers:
            recommendations.append("Add encryption (KMS) for data at rest protection")

        results.append({
            "arn": arn,
            "found": True,
            "node_type": node_type,
            "label": node_data.get("label", arn),
            "paths_from_internet": len(internet_paths),
            "shortest_internet_path": min((p["hops"] for p in internet_paths), default=None),
            "internet_paths": internet_paths[:5],
            "total_identities": len(identities),
            "human_identities": len(human_identities),
            "service_identities": len(service_identities),
            "external_identities": len(external_identities),
            "defense_layers": defense_layers,
            "defense_score": defense_score,
            "related_findings": len(related_findings),
            "recommendations": recommendations,
        })

    return results
