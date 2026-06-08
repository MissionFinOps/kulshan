"""Scan comparison / diff, show what changed between two scans."""

import json
from typing import Dict, List, Optional


def load_previous(path: str) -> Optional[Dict]:
    """Load a previous scan JSON file."""
    try:
        with open(path) as f:
            return json.load(f)
    except Exception:
        return None


def compare_scans(current_findings: List[Dict], previous: Dict) -> Dict:
    """Compare current scan to previous scan results."""
    prev_findings = {f["check_id"] + ":" + f["resource_id"]: f for f in previous.get("findings", [])}
    curr_findings = {f["check_id"] + ":" + f["resource_id"]: f for f in current_findings}

    new_findings = []
    resolved_findings = []
    persistent_findings = []

    for key, f in curr_findings.items():
        if key in prev_findings:
            persistent_findings.append(f)
        else:
            new_findings.append(f)

    for key, f in prev_findings.items():
        if key not in curr_findings:
            resolved_findings.append(f)

    prev_score = previous.get("scores", {}).get("overall_score", 0)
    curr_score = 0  # Will be set by caller

    return {
        "new_findings": new_findings,
        "resolved_findings": resolved_findings,
        "persistent_findings": persistent_findings,
        "new_count": len(new_findings),
        "resolved_count": len(resolved_findings),
        "persistent_count": len(persistent_findings),
        "previous_score": prev_score,
        "previous_grade": previous.get("scores", {}).get("overall_grade", "?"),
        "previous_total": len(prev_findings),
    }
