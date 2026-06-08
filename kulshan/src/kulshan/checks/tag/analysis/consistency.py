"""Tag value consistency analysis, detect chaos in tag values."""

from typing import Dict, List
from collections import defaultdict, Counter
import re


def analyze_consistency(resources, tag_keys=None):
    """Analyze tag value consistency and detect entropy/chaos."""
    if tag_keys is None:
        # Auto-detect most common tag keys
        key_counts = Counter()
        for r in resources:
            for k in r.get("tags", {}):
                key_counts[k] += 1
        tag_keys = [k for k, _ in key_counts.most_common(20)]

    results = {}
    for key in tag_keys:
        values = []
        for r in resources:
            v = r.get("tags", {}).get(key)
            if v is not None:
                values.append(v)

        if not values:
            continue

        value_counts = Counter(values)
        unique_values = len(value_counts)
        total_tagged = len(values)

        # Detect similar values (case variations, abbreviations)
        clusters = _cluster_similar_values(value_counts)

        # Entropy: unique values / total tagged resources
        # Low entropy = good governance, high entropy = chaos
        entropy = unique_values / total_tagged if total_tagged > 0 else 0

        results[key] = {
            "total_tagged": total_tagged,
            "unique_values": unique_values,
            "entropy": entropy,
            "top_values": value_counts.most_common(10),
            "clusters": clusters,
            "chaos_level": "Low" if entropy < 0.1 else "Medium" if entropy < 0.3 else "High",
        }

    return results


def _cluster_similar_values(value_counts):
    """Group similar values (case variations, common abbreviations)."""
    clusters = []
    seen = set()
    values = list(value_counts.keys())

    for i, v1 in enumerate(values):
        if v1 in seen:
            continue
        cluster = [(v1, value_counts[v1])]
        seen.add(v1)
        for v2 in values[i+1:]:
            if v2 in seen:
                continue
            if _are_similar(v1, v2):
                cluster.append((v2, value_counts[v2]))
                seen.add(v2)
        if len(cluster) > 1:
            # Sort by count descending, first one is the "canonical" value
            cluster.sort(key=lambda x: -x[1])
            total_resources = sum(c for _, c in cluster)
            clusters.append({
                "canonical": cluster[0][0],
                "variations": cluster,
                "total_resources": total_resources,
                "fixable": total_resources - cluster[0][1],
            })

    return clusters


def _are_similar(a, b):
    """Check if two tag values are likely the same thing."""
    a_lower = a.lower().strip().replace("-", "").replace("_", "").replace(" ", "")
    b_lower = b.lower().strip().replace("-", "").replace("_", "").replace(" ", "")
    if a_lower == b_lower:
        return True
    # Common abbreviations
    abbrevs = {
        "prod": "production", "dev": "development", "stg": "staging",
        "prd": "production", "qa": "qualityassurance", "uat": "useracceptancetesting",
    }
    a_norm = abbrevs.get(a_lower, a_lower)
    b_norm = abbrevs.get(b_lower, b_lower)
    return a_norm == b_norm
