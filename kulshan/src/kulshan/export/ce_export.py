"""Scoped Cost Explorer evidence export.

Produces separate Parquet files for each CE dimension. Full pagination.
Truncation is a hard failure.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd

from kulshan.export.scope import EvidenceScope
from kulshan.pseudonym.engine import PseudonymizationEngine
from kulshan.pseudonym.types import IdentifierClass


# CE dimensions to export
CE_DIMENSIONS = [
    ("service", "SERVICE"),
    ("account", "LINKED_ACCOUNT"),
    ("region", "REGION"),
    ("usage_type", "USAGE_TYPE"),
    ("operation", "OPERATION"),
    ("instance_type", "INSTANCE_TYPE"),
    ("charge_type", "RECORD_TYPE"),
]

CE_CROSS_DIMENSIONS = [
    ("service_account", ["SERVICE", "LINKED_ACCOUNT"]),
]


@dataclass
class CeExportResult:
    """Result of CE evidence export."""
    datasets: list[str]
    total_rows: int
    output_dir: Path
    truncated: bool = False


def export_ce(
    session: Any,
    scope: EvidenceScope,
    engine: PseudonymizationEngine,
    output_dir: Path,
) -> CeExportResult:
    """Export scoped Cost Explorer evidence as Parquet datasets.

    Args:
        session: boto3 session.
        scope: EvidenceScope for filtering.
        engine: PseudonymizationEngine (consultant-strict).
        output_dir: Directory for output Parquet files.

    Returns:
        CeExportResult.

    Raises:
        CeTruncationError: If pagination indicates truncated results.
    """
    from kulshan.aws_runtime import BOTO_CONFIG

    ce_client = session.client("ce", region_name="us-east-1", config=BOTO_CONFIG)
    output_dir.mkdir(parents=True, exist_ok=True)

    datasets = []
    total_rows = 0
    start = scope.from_date.isoformat()
    end = scope.to_date.isoformat()
    ce_filter = scope.ce_filter()

    # Single-dimension datasets
    for dim_name, dim_key in CE_DIMENSIONS:
        df = _fetch_dimension(ce_client, start, end, dim_key, ce_filter)
        if df.empty:
            continue

        # Pseudonymize account dimension values
        if dim_key == "LINKED_ACCOUNT":
            df["dimension_value"] = df["dimension_value"].apply(
                lambda v: engine.pseudonymize_value(v, IdentifierClass.ACCOUNT) if v else v
            )

        out_path = output_dir / f"{dim_name}.parquet"
        df.to_parquet(out_path, engine="pyarrow", compression="zstd", index=False)
        datasets.append(dim_name)
        total_rows += len(df)

    # Cross-dimension datasets
    for name, keys in CE_CROSS_DIMENSIONS:
        df = _fetch_cross_dimension(ce_client, start, end, keys, ce_filter)
        if df.empty:
            continue

        # Pseudonymize account values in cross-dimension
        if "account" in df.columns:
            df["account"] = df["account"].apply(
                lambda v: engine.pseudonymize_value(v, IdentifierClass.ACCOUNT) if v else v
            )

        out_path = output_dir / f"{name}.parquet"
        df.to_parquet(out_path, engine="pyarrow", compression="zstd", index=False)
        datasets.append(name)
        total_rows += len(df)

    return CeExportResult(
        datasets=datasets,
        total_rows=total_rows,
        output_dir=output_dir,
    )


def _fetch_dimension(
    client: Any,
    start: str,
    end: str,
    dim_key: str,
    ce_filter: dict | None,
) -> pd.DataFrame:
    """Fetch CE data grouped by a single dimension with full pagination."""
    results = []
    next_token = None
    page = 0
    max_pages = 50  # Hard limit to prevent runaway pagination

    while True:
        kwargs: dict[str, Any] = {
            "TimePeriod": {"Start": start, "End": end},
            "Granularity": "MONTHLY",
            "Metrics": ["UnblendedCost", "UsageQuantity"],
            "GroupBy": [{"Type": "DIMENSION", "Key": dim_key}],
        }
        if ce_filter:
            kwargs["Filter"] = ce_filter
        if next_token:
            kwargs["NextPageToken"] = next_token

        resp = client.get_cost_and_usage(**kwargs)
        results.extend(resp.get("ResultsByTime", []))
        next_token = resp.get("NextPageToken")
        page += 1

        if not next_token:
            break
        if page >= max_pages:
            raise CeTruncationError(
                f"CE pagination exceeded {max_pages} pages for dimension {dim_key}. "
                "Narrow the EvidenceScope."
            )

    rows = []
    for period in results:
        period_start = period["TimePeriod"]["Start"]
        for group in period.get("Groups", []):
            rows.append({
                "period": period_start,
                "dimension_value": group["Keys"][0],
                "unblended_cost": float(group["Metrics"]["UnblendedCost"]["Amount"]),
                "usage_quantity": float(group["Metrics"]["UsageQuantity"]["Amount"]),
            })

    return pd.DataFrame(rows) if rows else pd.DataFrame()


def _fetch_cross_dimension(
    client: Any,
    start: str,
    end: str,
    keys: list[str],
    ce_filter: dict | None,
) -> pd.DataFrame:
    """Fetch CE data grouped by two dimensions."""
    results = []
    next_token = None
    page = 0
    max_pages = 50

    while True:
        kwargs: dict[str, Any] = {
            "TimePeriod": {"Start": start, "End": end},
            "Granularity": "MONTHLY",
            "Metrics": ["UnblendedCost"],
            "GroupBy": [{"Type": "DIMENSION", "Key": k} for k in keys],
        }
        if ce_filter:
            kwargs["Filter"] = ce_filter
        if next_token:
            kwargs["NextPageToken"] = next_token

        resp = client.get_cost_and_usage(**kwargs)
        results.extend(resp.get("ResultsByTime", []))
        next_token = resp.get("NextPageToken")
        page += 1

        if not next_token:
            break
        if page >= max_pages:
            raise CeTruncationError(
                f"CE cross-dimension pagination exceeded {max_pages} pages. "
                "Narrow the EvidenceScope."
            )

    rows = []
    for period in results:
        period_start = period["TimePeriod"]["Start"]
        for group in period.get("Groups", []):
            row = {
                "period": period_start,
                "service": group["Keys"][0],
                "account": group["Keys"][1] if len(group["Keys"]) > 1 else "",
                "unblended_cost": float(group["Metrics"]["UnblendedCost"]["Amount"]),
            }
            rows.append(row)

    return pd.DataFrame(rows) if rows else pd.DataFrame()


class CeTruncationError(Exception):
    """CE pagination was truncated. This is a hard failure."""
    pass
