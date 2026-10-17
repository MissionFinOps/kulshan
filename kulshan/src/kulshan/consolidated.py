"""Consolidated payer report execution.

Runs packs across multiple approved AWS connections in a payer workspace,
deduplicates findings, and produces one coherent report.

Key rules:
- Cost pack runs ONLY from the authoritative cost connection (payer account
  or explicitly configured cost_connection). Never from an arbitrary member.
- Account-scoped packs run from each connection.
- Findings are deduplicated by composite key (fingerprint + account_id).
- Duplicate cost totals are never summed.
- One parent scan is saved to canonical history.
- Connection execution metadata is stored separately in one transaction.
- Payer cost coverage is tracked separately from report operational status.
"""
from __future__ import annotations

import logging
import time
from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any, Dict, List, Literal, Optional

from kulshan.orchestrator import run_all_scans, compute_overall, summarize_completeness
from kulshan.workspace.sts import create_verified_session, StsVerificationError

logger = logging.getLogger(__name__)

# Packs that require payer-account authority to produce payer-wide data.
PAYER_SCOPED_PACKS = frozenset({"cost"})

# All other packs are account-scoped.
ACCOUNT_SCOPED_PACKS = frozenset({"security", "sweep", "dr", "age", "drift", "tag", "pulse", "limit", "topo"})

ReportStatus = Literal["complete", "partial", "unavailable", "failed"]
PayerCostCoverage = Literal["verified_payer_wide", "account_scoped", "unavailable", "cur_authoritative"]


@dataclass
class ConnectionExecution:
    """Execution metadata for one connection."""

    connection_name: str
    profile: str | None
    session_account_id: str | None
    role_arn: str | None
    status: Literal["success", "failed", "skipped"]
    duration_seconds: float = 0.0
    packs_attempted: list[str] = field(default_factory=list)
    packs_completed: list[str] = field(default_factory=list)
    error_code: str | None = None


@dataclass
class ConsolidatedResult:
    """Result of a consolidated multi-connection report."""

    results: Dict[str, dict]
    all_findings: list[dict]
    overall_score: int
    overall_grade: str
    report_status: ReportStatus
    payer_cost_coverage: PayerCostCoverage
    connections_executed: list[ConnectionExecution]
    accounts_observed: list[str]
    duration_seconds: float
    payer_connection: str | None = None
    payer_account_id: str | None = None

    @property
    def successful_connections(self) -> list[ConnectionExecution]:
        return [c for c in self.connections_executed if c.status == "success"]

    @property
    def failed_connections(self) -> list[ConnectionExecution]:
        return [c for c in self.connections_executed if c.status == "failed"]


def resolve_cost_authority(
    connections: list[dict],
    payer_account_id: str | None,
    cost_connection_name: str | None,
) -> dict | None:
    """Determine which connection has authority for payer-wide cost data.

    Selection order:
    1. Explicitly configured cost_connection.
    2. A connection whose expected_session_account_id == payer_account_id.
    3. None — no payer-wide cost authority available.

    An arbitrary member account connection is NEVER selected.

    Args:
        connections: List of connection config dicts.
        payer_account_id: Verified payer account (may be None).
        cost_connection_name: Explicit cost_connection config (may be None).

    Returns:
        The authoritative connection dict, or None.
    """
    # 1. Explicit cost_connection
    if cost_connection_name:
        for conn in connections:
            if conn["name"] == cost_connection_name:
                return conn
        logger.warning("Configured cost_connection '%s' not found.", cost_connection_name)

    # 2. Connection matching payer account
    if payer_account_id:
        for conn in connections:
            if conn["expected_session_account_id"] == payer_account_id:
                return conn

    # 3. No authority
    return None


def run_consolidated_report(
    connections: list[dict],
    regions: list[str],
    selected_packs: list[str],
    *,
    payer_account_id: str | None = None,
    cost_connection_name: str | None = None,
    quick: bool = False,
    deep: bool = False,
    days: int = 90,
    console: Any = None,
) -> ConsolidatedResult:
    """Run a consolidated report across multiple connections.

    Each connection dict must have:
        name: str
        profile: str
        role_arn: str | None
        expected_session_account_id: str

    Args:
        connections: List of connection configs.
        regions: AWS regions to scan.
        selected_packs: Packs to run.
        payer_account_id: Verified payer account ID (for cost authority).
        cost_connection_name: Explicit cost authority connection name.
        quick: Skip confirmations.
        deep: Run expensive checks.
        days: Cost analysis lookback.
        console: Rich console for output.

    Returns:
        ConsolidatedResult with merged, deduplicated findings.
    """
    from rich.console import Console

    if console is None:
        console = Console()

    start_time = time.time()
    connection_executions: list[ConnectionExecution] = []
    all_pack_results: Dict[str, list[dict]] = {}
    all_findings_raw: list[dict] = []
    accounts_observed: set[str] = set()
    payer_connection_used: str | None = None
    payer_cost_coverage: PayerCostCoverage = "unavailable"

    # Determine cost authority
    payer_packs = [p for p in selected_packs if p in PAYER_SCOPED_PACKS]
    account_packs = [p for p in selected_packs if p in ACCOUNT_SCOPED_PACKS]

    cost_authority = resolve_cost_authority(
        connections, payer_account_id, cost_connection_name
    )

    default_conn = connections[0] if connections else None

    for conn in connections:
        conn_name = conn["name"]
        profile = conn["profile"]
        role_arn = conn.get("role_arn")
        expected_account = conn["expected_session_account_id"]

        conn_start = time.time()
        packs_attempted: list[str] = []
        packs_completed: list[str] = []

        # Verify credentials
        try:
            verified = create_verified_session(
                profile=profile,
                role_arn=role_arn,
            )
        except StsVerificationError as e:
            if conn == default_conn:
                exec_meta = ConnectionExecution(
                    connection_name=conn_name, profile=profile,
                    session_account_id=None, role_arn=role_arn,
                    status="failed", duration_seconds=time.time() - conn_start,
                    error_code="sts_verification_failed",
                )
                connection_executions.append(exec_meta)
                raise DefaultConnectionFailedError(conn_name, str(e)) from e

            exec_meta = ConnectionExecution(
                connection_name=conn_name, profile=profile,
                session_account_id=None, role_arn=role_arn,
                status="failed", duration_seconds=time.time() - conn_start,
                error_code="sts_verification_failed",
            )
            connection_executions.append(exec_meta)
            logger.warning("Connection '%s' unavailable: %s", conn_name, e)
            continue

        # Credential mismatch check
        if verified.account_id != expected_account:
            exec_meta = ConnectionExecution(
                connection_name=conn_name, profile=profile,
                session_account_id=verified.account_id, role_arn=role_arn,
                status="failed", duration_seconds=time.time() - conn_start,
                error_code="credential_mismatch",
            )
            connection_executions.append(exec_meta)

            if conn == default_conn:
                raise DefaultConnectionFailedError(
                    conn_name,
                    f"Credential mismatch: expected {expected_account}, got {verified.account_id}",
                )
            continue

        session = verified.session
        accounts_observed.add(verified.account_id)

        # Determine which packs this connection should run
        conn_packs: list[str] = list(account_packs)

        # Payer-scoped packs: ONLY from authoritative cost connection
        if conn == cost_authority and payer_packs:
            conn_packs = payer_packs + conn_packs
            payer_connection_used = conn_name

        if not conn_packs:
            exec_meta = ConnectionExecution(
                connection_name=conn_name, profile=profile,
                session_account_id=verified.account_id, role_arn=role_arn,
                status="success", duration_seconds=time.time() - conn_start,
            )
            connection_executions.append(exec_meta)
            continue

        packs_attempted = list(conn_packs)

        # Run packs
        try:
            results = run_all_scans(
                session, regions, profile=profile,
                quick=quick, console=console,
                selected_packs=conn_packs, deep=deep, days=days,
            )
        except Exception as e:
            exec_meta = ConnectionExecution(
                connection_name=conn_name, profile=profile,
                session_account_id=verified.account_id, role_arn=role_arn,
                status="failed", duration_seconds=time.time() - conn_start,
                packs_attempted=packs_attempted,
                error_code=f"scan_error: {type(e).__name__}",
            )
            connection_executions.append(exec_meta)
            if conn == default_conn:
                raise DefaultConnectionFailedError(conn_name, str(e)) from e
            continue

        # Collect results
        for pack_name, pack_result in results.items():
            pack_result = deepcopy(pack_result)
            pack_result["source_connections"] = [conn_name]
            if pack_name not in all_pack_results:
                all_pack_results[pack_name] = []
            all_pack_results[pack_name].append(pack_result)

            for finding in pack_result.get("findings", []):
                finding["_source_connections"] = [conn_name]
                # Ensure account_id is tagged for deduplication
                if "account_id" not in finding or not finding["account_id"]:
                    finding["account_id"] = verified.account_id
                all_findings_raw.append(finding)

            if summarize_completeness({pack_name: pack_result})["status"] == "complete":
                packs_completed.append(pack_name)

        exec_meta = ConnectionExecution(
            connection_name=conn_name, profile=profile,
            session_account_id=verified.account_id, role_arn=role_arn,
            status="success", duration_seconds=time.time() - conn_start,
            packs_attempted=packs_attempted, packs_completed=packs_completed,
        )
        connection_executions.append(exec_meta)

    # Check if any connections succeeded
    successful = [c for c in connection_executions if c.status == "success"]
    if not successful:
        raise NoSuccessfulConnectionsError(
            [c.connection_name for c in connection_executions]
        )

    # Determine payer cost coverage
    if payer_connection_used:
        payer_cost_coverage = "verified_payer_wide"
    elif payer_packs and any(
        p in all_pack_results for p in payer_packs
    ):
        # Cost ran but not from payer authority — label as account_scoped
        payer_cost_coverage = "account_scoped"
    elif payer_packs:
        payer_cost_coverage = "unavailable"

    # Failed connections must remain represented in the packs they should cover.
    for execution in connection_executions:
        if execution.status != "failed":
            continue
        expected_packs = list(account_packs)
        if cost_authority and execution.connection_name == cost_authority["name"]:
            expected_packs += payer_packs
        for pack_name in expected_packs:
            all_pack_results.setdefault(pack_name, []).append({
                "skipped": True, "errors": [execution.error_code or "Connection unavailable"],
                "source_connections": [execution.connection_name], "findings": [],
            })
    for pack_name in selected_packs:
        all_pack_results.setdefault(pack_name, [{
            "skipped": True, "errors": ["No eligible connection executed this pack"],
            "findings": [], "source_connections": [],
        }])

    # Merge pack results
    merged_results: Dict[str, dict] = {}
    for pack_name, result_list in all_pack_results.items():
        merged_results[pack_name] = _merge_pack_results(result_list)
    if "cost" in merged_results and merged_results["cost"].get("skipped"):
        payer_cost_coverage = "unavailable"

    # Deduplicate findings (account-aware)
    deduped_findings = deduplicate_findings(all_findings_raw)

    # Compute overall score
    overall_score, overall_grade = compute_overall(merged_results)

    # Determine report status
    report_status = summarize_completeness(merged_results)["status"]

    duration = time.time() - start_time

    return ConsolidatedResult(
        results=merged_results,
        all_findings=deduped_findings,
        overall_score=overall_score,
        overall_grade=overall_grade,
        report_status=report_status,
        payer_cost_coverage=payer_cost_coverage,
        connections_executed=connection_executions,
        accounts_observed=sorted(accounts_observed),
        duration_seconds=duration,
        payer_connection=payer_connection_used,
        payer_account_id=payer_account_id,
    )


def _merge_pack_results(result_list: list[dict]) -> dict:
    """Merge multiple account-scoped results for the same pack."""
    if not result_list:
        return {}

    base = None
    for r in result_list:
        if not r.get("skipped"):
            base = deepcopy(r)
            break
    if base is None:
        base = deepcopy(result_list[0])

    coverage = summarize_completeness({str(i): r for i, r in enumerate(deepcopy(result_list))})
    base["errors"] = list(dict.fromkeys(
        str(error) for result in result_list for error in result.get("errors", [])
    ))
    base["missing_permissions"] = sorted({
        value for result in result_list for value in result.get("missing_permissions", [])
    })
    base["source_connections"] = sorted({
        value for result in result_list for value in result.get("source_connections", [])
    })
    base["coverage_by_source"] = [
        {"source_connections": result.get("source_connections", []),
         "coverage": summarize_completeness({"pack": deepcopy(result)}),
         "region_coverage": deepcopy(result.get("coverage", {})),
         "metadata": deepcopy(result.get("metadata", {})),
         "errors": result.get("errors", [])}
        for result in result_list
    ]
    base["skipped"] = coverage["status"] == "unavailable"
    base["partial"] = coverage["partial"]
    base["completeness"] = "partial" if coverage["partial"] else "complete"

    all_findings = []
    for r in result_list:
        all_findings.extend(r.get("findings", []))
    base["findings"] = all_findings

    scores = base.setdefault("scores", {})
    scores["total_findings"] = len(all_findings)
    counts: dict[str, int] = {}
    for finding in all_findings:
        severity = finding.get("severity", "info")
        counts[severity] = counts.get(severity, 0) + finding.get("grouped_count", 1)
    scores["severity_counts"] = counts
    known_scores = [result.get("scores", {}).get("overall_score") for result in result_list]
    if coverage["partial"] or any(score is None for score in known_scores):
        scores["overall_score"], scores["grade"] = None, "N/A"
    else:
        # Do not silently present the first account's score as a combined score.
        scores["overall_score"] = min(known_scores)
        from kulshan.orchestrator import _grade
        scores["grade"] = _grade(scores["overall_score"])

    return base


def deduplicate_findings(findings: list[dict]) -> list[dict]:
    """Deduplicate findings by composite key: fingerprint + account_id.

    The same finding type on two different accounts MUST remain two
    separate findings. Only identical resource evidence seen through
    multiple connections (same account, same fingerprint) deduplicates.

    Rules:
    - Composite key = fingerprint + account_id.
    - Same key from multiple connections → one finding.
    - Prefer the higher-confidence record.
    - Retain all contributing connection names.
    - Never sum duplicate cost totals.

    Args:
        findings: Raw findings list (may contain duplicates).

    Returns:
        Deduplicated findings list.
    """
    seen: Dict[str, dict] = {}  # composite_key -> best finding

    for finding in findings:
        fp = finding.get("fingerprint", "")
        account = finding.get("account_id", "")

        if not fp:
            # No fingerprint — treat as unique
            key = str(id(finding))
        else:
            # Composite key includes account so different accounts stay separate
            key = f"{fp}|{account}"

        if key not in seen:
            seen[key] = finding
        else:
            existing = seen[key]
            # Merge source connections
            existing_sources = existing.get("_source_connections", [])
            new_sources = finding.get("_source_connections", [])
            merged_sources = list(set(existing_sources + new_sources))
            existing["_source_connections"] = merged_sources

            # Prefer higher confidence
            existing_conf = existing.get("confidence", 0)
            new_conf = finding.get("confidence", 0)
            if new_conf > existing_conf:
                finding["_source_connections"] = merged_sources
                seen[key] = finding

    return list(seen.values())


class DefaultConnectionFailedError(Exception):
    """Default connection credential failure — abort before persistence."""

    def __init__(self, connection_name: str, reason: str):
        self.connection_name = connection_name
        self.reason = reason
        super().__init__(
            f"Default connection '{connection_name}' failed: {reason}"
        )


class NoSuccessfulConnectionsError(Exception):
    """No connections succeeded — cannot produce a report."""

    def __init__(self, attempted: list[str]):
        self.attempted = attempted
        super().__init__(
            f"No successful connections. Attempted: {', '.join(attempted)}"
        )
