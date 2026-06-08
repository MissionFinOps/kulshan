"""CSV export for Kulshan findings — spreadsheet-friendly format."""
from __future__ import annotations

import csv
import io
from typing import List


CSV_COLUMNS = [
    "severity",
    "pack",
    "kind",
    "title",
    "resource_id",
    "region",
    "confidence",
    "effort",
    "risk",
    "estimated_monthly_impact",
    "recommended_action",
    "remediation_snippet",
]


def findings_to_csv(findings: List[dict]) -> str:
    """Convert a list of canonical findings to a CSV string.

    Sorted by severity (critical first), then by monthly impact descending.
    """
    severity_order = {"critical": 0, "high": 1, "medium": 2, "low": 3, "info": 4}

    sorted_findings = sorted(
        findings,
        key=lambda f: (
            severity_order.get(f.get("severity", "info"), 5),
            -(float(f.get("estimated_monthly_impact", 0) or 0)),
        ),
    )

    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=CSV_COLUMNS, extrasaction="ignore")
    writer.writeheader()

    for finding in sorted_findings:
        row = {}
        for col in CSV_COLUMNS:
            val = finding.get(col, "")
            if val is None:
                val = ""
            # Flatten multi-line remediation for CSV
            if isinstance(val, str):
                val = val.replace("\n", " | ")
            row[col] = val
        writer.writerow(row)

    return output.getvalue()
