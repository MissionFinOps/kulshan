"""CUR-based payer binding for workspaces.

Extracts bill_payer_account_id from local CUR data and binds it to
the workspace. This is the integration layer between the CUR reader
and the workspace configuration.

No boto3 or STS calls are made during binding — it's entirely local.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Any, Literal

from kulshan.workspace.context import WorkspaceContext
from kulshan.workspace.onboarding import (
    PayerBindingConflictError,
    PayerBindingError,
    bind_payer_account,
)

logger = logging.getLogger(__name__)

# 12-digit AWS account ID pattern
_ACCOUNT_ID_PATTERN = re.compile(r"^\d{12}$")


@dataclass
class PayerBindingResult:
    """Result of attempting to bind a payer from CUR evidence."""

    status: Literal["bound", "already_bound", "missing", "conflict", "multiple", "invalid"]
    payer_account_id: str | None = None
    message: str | None = None


class InvalidPayerEvidenceError(Exception):
    """CUR contains a non-empty payer value that is not a valid 12-digit account."""

    def __init__(self, value: str):
        self.value = value
        super().__init__(
            f"Invalid payer account evidence in CUR: '{value}' "
            f"is not a valid 12-digit AWS account ID."
        )


class MultiplePayerEvidenceError(Exception):
    """CUR contains multiple distinct payer account IDs."""

    def __init__(self, payer_ids: list[str]):
        self.payer_ids = payer_ids
        super().__init__(
            f"CUR contains multiple payer accounts ({', '.join(payer_ids)}). "
            "Cannot bind workspace to multiple payers."
        )


def extract_payer_from_cur(con: Any) -> str | None:
    """Extract the single payer account ID from a CUR DuckDB connection.

    Queries the cur_raw view for distinct bill_payer_account_id values.

    Args:
        con: DuckDB connection with cur_raw view registered.

    Returns:
        The 12-digit payer account ID, or None if no payer column/data exists.

    Raises:
        InvalidPayerEvidenceError: Non-empty value that isn't 12 digits.
        MultiplePayerEvidenceError: Multiple distinct payer IDs found.
    """
    # Standard CUR column names for billing/payer account
    payer_column_candidates = (
        "bill_payer_account_id",
        "bill_payeraccountid",
        "payer_account_id",
    )

    # Find which payer column exists
    try:
        columns = {
            str(row[0]).lower()
            for row in con.execute("DESCRIBE cur_raw").fetchall()
        }
    except Exception:
        return None

    payer_column = None
    for candidate in payer_column_candidates:
        if candidate in columns:
            payer_column = candidate
            break

    if payer_column is None:
        return None  # No payer evidence available

    # Query distinct non-null, non-empty payer values
    try:
        rows = con.execute(
            f"SELECT DISTINCT CAST({payer_column} AS VARCHAR) "
            f"FROM cur_raw "
            f"WHERE {payer_column} IS NOT NULL "
            f"AND CAST({payer_column} AS VARCHAR) != ''"
        ).fetchall()
    except Exception:
        return None

    payer_values = sorted(set(str(row[0]).strip() for row in rows))

    if not payer_values:
        return None  # No payer evidence

    # Validate each value is a proper 12-digit account ID
    for value in payer_values:
        if not _ACCOUNT_ID_PATTERN.match(value):
            raise InvalidPayerEvidenceError(value)

    # Multiple distinct payers
    if len(payer_values) > 1:
        raise MultiplePayerEvidenceError(payer_values)

    return payer_values[0]


def try_bind_payer_from_cur(
    con: Any,
    ws_ctx: WorkspaceContext,
) -> PayerBindingResult:
    """Attempt to bind a workspace to its payer using CUR evidence.

    This is the main integration point called from investigate commands.
    It extracts the payer, validates it, and binds the workspace.

    No boto3 or STS calls. Entirely local operation.

    Args:
        con: DuckDB connection with cur_raw view registered.
        ws_ctx: Resolved workspace context.

    Returns:
        PayerBindingResult describing what happened.

    Raises:
        InvalidPayerEvidenceError: CUR has invalid non-empty payer value.
        MultiplePayerEvidenceError: CUR has multiple payer accounts.
        PayerBindingConflictError: Workspace already bound to different payer.
    """
    if not ws_ctx.is_bound or ws_ctx.config.aws is None:
        return PayerBindingResult(
            status="missing",
            message="Workspace is not bound — cannot apply payer binding.",
        )

    # Extract payer from CUR
    payer_id = extract_payer_from_cur(con)

    if payer_id is None:
        # Rule 9: missing evidence — warn and continue
        return PayerBindingResult(
            status="missing",
            message="CUR does not contain payer account evidence. Continuing without binding.",
        )

    current_payer = ws_ctx.config.aws.payer_account_id

    # Rule 6: already bound to same payer
    if current_payer == payer_id:
        return PayerBindingResult(
            status="already_bound",
            payer_account_id=payer_id,
        )

    # Rule 7: bound to a different payer — conflict (raises)
    # Rule 1: no payer yet — bind (bind_payer_account handles both)
    bind_payer_account(ws_ctx.name, payer_id)

    return PayerBindingResult(
        status="bound",
        payer_account_id=payer_id,
        message=f"Bound this environment to payer {_redact_payer(payer_id)} using CUR evidence.",
    )


def _redact_payer(account_id: str) -> str:
    """Redact a 12-digit account ID to XXXX-XXXX-9999 format."""
    if len(account_id) == 12:
        return f"XXXX-XXXX-{account_id[8:]}"
    return account_id
