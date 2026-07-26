"""Read-only discovery and ranking for AWS Data Exports and legacy CUR."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal, Optional

from botocore.exceptions import ClientError

ExportProvider = Literal["data-exports", "legacy-cur"]
AuthorityScope = Literal["payer-connection", "account-scoped", "unverified"]


@dataclass
class CurExportInfo:
    """One discovered CUR-compatible export destination."""

    export_name: str
    export_arn: str
    s3_bucket: str
    s3_prefix: str
    format: str
    status: str
    provider: ExportProvider = "data-exports"
    s3_region: str = "us-east-1"
    s3_bucket_owner: str | None = None
    table_name: str | None = None
    query_statement: str | None = None
    last_refreshed_at: datetime | None = None
    authority_scope: AuthorityScope = "unverified"
    schema_compatible: bool | None = None
    accessible: bool | None = None

    @property
    def s3_uri(self) -> str:
        prefix = self.s3_prefix.strip("/")
        suffix = f"/{prefix}/" if prefix else "/"
        return f"s3://{self.s3_bucket}{suffix}"

    @property
    def selector(self) -> str:
        return self.export_arn or self.export_name


@dataclass(frozen=True)
class DiscoveryIssue:
    """A discovery operation that could not be completed."""

    provider: ExportProvider
    operation: str
    code: str
    message: str


@dataclass
class CurDiscoveryResult:
    """Discovered exports plus explicit unknowns."""

    exports: list[CurExportInfo] = field(default_factory=list)
    issues: list[DiscoveryIssue] = field(default_factory=list)


def _error_code(exc: Exception) -> str:
    if isinstance(exc, ClientError):
        return str(exc.response.get("Error", {}).get("Code", "ClientError"))
    return type(exc).__name__


def _issue(
    provider: ExportProvider,
    operation: str,
    exc: Exception,
) -> DiscoveryIssue:
    return DiscoveryIssue(
        provider=provider,
        operation=operation,
        code=_error_code(exc),
        message=str(exc),
    )


def _modern_exports(session: Any, result: CurDiscoveryResult) -> None:
    provider: ExportProvider = "data-exports"
    try:
        client = session.client("bcm-data-exports", region_name="us-east-1")
        paginator = client.get_paginator("list_exports")
        references = [
            export
            for page in paginator.paginate()
            for export in page.get("Exports", [])
        ]
    except Exception as exc:
        result.issues.append(_issue(provider, "ListExports", exc))
        return

    for reference in references:
        arn = str(reference.get("ExportArn") or "")
        if not arn:
            continue
        try:
            payload = client.get_export(ExportArn=arn).get("Export", {})
        except Exception as exc:
            result.issues.append(_issue(provider, f"GetExport:{arn}", exc))
            continue
        destination = payload.get("DestinationConfigurations", {}).get(
            "S3Destination", {}
        )
        bucket = str(destination.get("S3Bucket") or "")
        if not bucket:
            continue
        output = destination.get("S3OutputConfigurations", {})
        data_query = payload.get("DataQuery", {})
        table_configurations = data_query.get("TableConfigurations", {})
        table_name = next(iter(table_configurations), None)
        query = data_query.get("QueryStatement")
        if table_name is None and query:
            match = re.search(r"\bfrom\s+([A-Za-z0-9_]+)", str(query), re.I)
            table_name = match.group(1) if match else None
        export_status = payload.get("ExportStatus") or reference.get(
            "ExportStatus", {}
        )
        result.exports.append(
            CurExportInfo(
                export_name=str(
                    payload.get("Name")
                    or reference.get("ExportName")
                    or "unknown"
                ),
                export_arn=arn,
                s3_bucket=bucket,
                s3_prefix=str(destination.get("S3Prefix") or ""),
                format=str(output.get("Format") or "UNKNOWN").upper(),
                status=str(export_status.get("StatusCode") or "UNKNOWN").upper(),
                provider=provider,
                s3_region=str(destination.get("S3Region") or "us-east-1"),
                s3_bucket_owner=destination.get("S3BucketOwner"),
                table_name=str(table_name) if table_name else None,
                query_statement=str(query) if query else None,
                last_refreshed_at=export_status.get("LastRefreshedAt"),
            )
        )


def _legacy_exports(session: Any, result: CurDiscoveryResult) -> None:
    provider: ExportProvider = "legacy-cur"
    try:
        client = session.client("cur", region_name="us-east-1")
        token: str | None = None
        while True:
            kwargs = {"MaxResults": 100}
            if token:
                kwargs["NextToken"] = token
            page = client.describe_report_definitions(**kwargs)
            for report in page.get("ReportDefinitions", []):
                name = str(report.get("ReportName") or "unknown")
                bucket = str(report.get("S3Bucket") or "")
                if not bucket:
                    continue
                base_prefix = str(report.get("S3Prefix") or "").strip("/")
                prefix = "/".join(part for part in (base_prefix, name) if part)
                result.exports.append(
                    CurExportInfo(
                        export_name=name,
                        export_arn="",
                        s3_bucket=bucket,
                        s3_prefix=prefix,
                        format=str(report.get("Format") or "UNKNOWN").upper(),
                        status="HEALTHY",
                        provider=provider,
                        s3_region=str(report.get("S3Region") or "us-east-1"),
                        table_name="LEGACY_CUR",
                    )
                )
            token = page.get("NextToken")
            if not token:
                break
    except Exception as exc:
        result.issues.append(
            _issue(provider, "DescribeReportDefinitions", exc)
        )


def _deduplicate(exports: list[CurExportInfo]) -> list[CurExportInfo]:
    chosen: dict[tuple[str, str, str], CurExportInfo] = {}
    for export in exports:
        key = (
            export.s3_bucket.lower(),
            export.s3_prefix.strip("/").lower(),
            export.export_name.lower(),
        )
        existing = chosen.get(key)
        if existing is None or (
            existing.provider == "legacy-cur"
            and export.provider == "data-exports"
        ):
            chosen[key] = export
    return list(chosen.values())


def discover_cur_exports_detailed(
    session: Any,
    *,
    session_account_id: str | None = None,
    payer_account_id: str | None = None,
) -> CurDiscoveryResult:
    """Discover modern and legacy exports owned by the authenticated account."""
    result = CurDiscoveryResult()
    _modern_exports(session, result)
    _legacy_exports(session, result)
    result.exports = _deduplicate(result.exports)
    scope: AuthorityScope = "unverified"
    if session_account_id:
        scope = (
            "payer-connection"
            if payer_account_id and session_account_id == payer_account_id
            else "account-scoped"
        )
    for export in result.exports:
        export.authority_scope = scope
    return result


def discover_cur_exports(session: Any) -> list[CurExportInfo]:
    """Backward-compatible list-only discovery API."""
    return discover_cur_exports_detailed(session).exports


def _matches_selector(export: CurExportInfo, selector: str | None) -> bool:
    if not selector:
        return False
    normalized = selector.strip().rstrip("/")
    return normalized in {
        export.export_arn,
        export.export_name,
        export.s3_uri.rstrip("/"),
    }


def export_rank(
    export: CurExportInfo,
    *,
    preferred_selector: str | None = None,
) -> tuple[int, int, int, int, int, float]:
    """Return the documented primary ranking dimensions."""
    refreshed = (
        export.last_refreshed_at.timestamp()
        if export.last_refreshed_at is not None
        else 0.0
    )
    cost_table = (export.table_name or "").upper() in {
        "COST_AND_USAGE_REPORT",
        "LEGACY_CUR",
    }
    return (
        int(_matches_selector(export, preferred_selector)),
        int(export.authority_scope == "payer-connection"),
        int(export.status == "HEALTHY"),
        int(cost_table and export.schema_compatible is not False),
        int(export.format == "PARQUET"),
        refreshed,
    )


def rank_cur_exports(
    exports: list[CurExportInfo],
    *,
    preferred_selector: str | None = None,
) -> list[CurExportInfo]:
    """Rank candidates deterministically while preserving meaningful ties."""
    return sorted(
        exports,
        key=lambda export: (
            export_rank(export, preferred_selector=preferred_selector),
            export.export_name.lower(),
            export.export_arn,
        ),
        reverse=True,
    )


def tied_best_exports(
    exports: list[CurExportInfo],
    *,
    preferred_selector: str | None = None,
) -> list[CurExportInfo]:
    ranked = rank_cur_exports(exports, preferred_selector=preferred_selector)
    if not ranked:
        return []
    best_rank = export_rank(ranked[0], preferred_selector=preferred_selector)
    return [
        export
        for export in ranked
        if export_rank(export, preferred_selector=preferred_selector)
        == best_rank
    ]


def find_best_cur_export(
    session: Any,
    *,
    preferred_selector: str | None = None,
    session_account_id: str | None = None,
    payer_account_id: str | None = None,
) -> Optional[CurExportInfo]:
    result = discover_cur_exports_detailed(
        session,
        session_account_id=session_account_id,
        payer_account_id=payer_account_id,
    )
    ranked = rank_cur_exports(
        result.exports,
        preferred_selector=preferred_selector,
    )
    return ranked[0] if ranked else None


def check_cur_s3_access(session: Any, export: CurExportInfo) -> bool:
    """Verify listing plus readable manifest and Parquet evidence."""
    try:
        s3 = session.client("s3", region_name=export.s3_region)
        token: str | None = None
        manifest_key: str | None = None
        parquet_key: str | None = None
        while True:
            kwargs: dict[str, Any] = {
                "Bucket": export.s3_bucket,
                "Prefix": export.s3_prefix,
                "MaxKeys": 1000,
            }
            if token:
                kwargs["ContinuationToken"] = token
            response = s3.list_objects_v2(**kwargs)
            for item in response.get("Contents", []):
                key = str(item.get("Key", ""))
                if manifest_key is None and key.lower().endswith("manifest.json"):
                    manifest_key = key
                if parquet_key is None and key.lower().endswith(".parquet"):
                    parquet_key = key
            if manifest_key and parquet_key:
                break
            token = response.get("NextContinuationToken")
            if not response.get("IsTruncated") or not token:
                break
        if not manifest_key or not parquet_key:
            return False
        s3.head_object(Bucket=export.s3_bucket, Key=manifest_key)
        s3.head_object(Bucket=export.s3_bucket, Key=parquet_key)
        return True
    except Exception:
        return False
