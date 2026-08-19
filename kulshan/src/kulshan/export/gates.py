"""Fail-closed validation gates for consultant evidence export.

All three gates must pass before a ZIP is created.
Any failure deletes intermediate artifacts and exits non-zero.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from kulshan.export.columns import ColumnClass


# ---------------------------------------------------------------------------
# Gate results
# ---------------------------------------------------------------------------

@dataclass
class GateResult:
    passed: bool
    gate: str
    details: dict[str, Any] = field(default_factory=dict)
    failures: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Gate 1: Schema classification
# ---------------------------------------------------------------------------

def gate_schema(
    classification: dict[str, ColumnClass],
    drop_unclassified: bool = False,
) -> GateResult:
    """Every output column must be classified. No unclassified column survives.

    Args:
        classification: Dict of column_name -> ColumnClass.
        drop_unclassified: If True, unclassified columns are dropped (not blocked).

    Returns:
        GateResult with pass/fail and classification counts.
    """
    counts = {c: 0 for c in ColumnClass}
    unclassified = []
    for col, cls in classification.items():
        counts[cls] += 1
        if cls == ColumnClass.UNCLASSIFIED:
            unclassified.append(col)

    if unclassified and not drop_unclassified:
        return GateResult(
            passed=False,
            gate="schema",
            details={"counts": {k.value: v for k, v in counts.items()}, "total": len(classification)},
            failures=[f"Unclassified column: {col}" for col in sorted(unclassified)],
        )

    return GateResult(
        passed=True,
        gate="schema",
        details={
            "counts": {k.value: v for k, v in counts.items()},
            "total": len(classification),
            "dropped_unclassified": sorted(unclassified) if drop_unclassified else [],
        },
    )


# ---------------------------------------------------------------------------
# Gate 2: Evidence integrity
# ---------------------------------------------------------------------------

def gate_integrity(
    source_row_count: int,
    output_row_count: int,
    source_cost_bytes: bytes | None = None,
    output_cost_bytes: bytes | None = None,
) -> GateResult:
    """Row count and cost byte-identity between source and output.

    Args:
        source_row_count: Number of rows in scoped source.
        output_row_count: Number of rows in output parquet.
        source_cost_bytes: Raw bytes of cost column sample (optional).
        output_cost_bytes: Raw bytes of same cost column from output (optional).
    """
    failures = []

    if source_row_count != output_row_count:
        failures.append(
            f"Row count mismatch: source={source_row_count}, output={output_row_count}"
        )

    if source_cost_bytes is not None and output_cost_bytes is not None:
        if source_cost_bytes != output_cost_bytes:
            failures.append("Cost column bytes differ between source and output")

    return GateResult(
        passed=len(failures) == 0,
        gate="integrity",
        details={
            "source_rows": source_row_count,
            "output_rows": output_row_count,
        },
        failures=failures,
    )


# ---------------------------------------------------------------------------
# Gate 3: Residual identifier scan
# ---------------------------------------------------------------------------

_ACCOUNT_RE = re.compile(r"\b\d{12}\b")
_ARN_RE = re.compile(r"arn:aws[a-z-]*:[a-z0-9-]+:[a-z0-9-]*:\d{12}:[^\s,\"']+")
_EMAIL_RE = re.compile(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}")
_IPV4_RE = re.compile(r"\b(?:10|172\.(?:1[6-9]|2\d|3[01])|192\.168)\.\d{1,3}\.\d{1,3}\b")
_BUCKET_RE = re.compile(r"\b[a-z0-9][a-z0-9.\-]{1,61}[a-z0-9]\b")


def gate_residual(
    source_identifiers: set[str],
    output_text: str,
    secret_path: Path | None = None,
) -> GateResult:
    """Scan output for residual source identifiers and generic patterns.

    Args:
        source_identifiers: Set of real identifier values from PSEUDONYMIZE columns.
        output_text: Concatenated text content of all output files.
        secret_path: Path to workspace pseudonym.key (must not be in ZIP).
    """
    failures = []

    # Check source identifiers don't appear in output
    for identifier in source_identifiers:
        if identifier and len(identifier) >= 4 and identifier in output_text:
            failures.append(f"Source identifier leaked (length {len(identifier)})")
            # Do not print the value itself

    # Generic pattern scan
    account_matches = _ACCOUNT_RE.findall(output_text)
    # Filter out known-safe patterns (years, timestamps)
    real_accounts = [m for m in account_matches if not _is_likely_non_account(m)]
    if real_accounts:
        failures.append(f"Potential 12-digit account ID pattern found ({len(real_accounts)} occurrences)")

    arn_matches = _ARN_RE.findall(output_text)
    if arn_matches:
        failures.append(f"ARN pattern found ({len(arn_matches)} occurrences)")

    email_matches = _EMAIL_RE.findall(output_text)
    # Filter pseudo.invalid emails (those are our aliases)
    real_emails = [e for e in email_matches if not e.endswith("pseudo.invalid")]
    if real_emails:
        failures.append(f"Email pattern found ({len(real_emails)} occurrences)")

    # Assert key material not present
    if secret_path and secret_path.exists():
        secret_hex = secret_path.read_bytes().hex()
        if secret_hex in output_text:
            failures.append("Workspace secret key material found in output")

    return GateResult(
        passed=len(failures) == 0,
        gate="residual",
        details={"identifiers_checked": len(source_identifiers)},
        failures=failures,
    )


def _is_likely_non_account(value: str) -> bool:
    """Heuristic: is this 12-digit string likely NOT an account ID?"""
    # Timestamps in milliseconds often look like 12-digit numbers
    # Account IDs don't start with 0
    if value.startswith("0"):
        return True
    # Very round numbers are unlikely accounts
    if value.endswith("000000"):
        return True
    return False
