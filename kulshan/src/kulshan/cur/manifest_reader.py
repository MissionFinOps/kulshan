"""S3 CUR/Data Export manifest reader."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

import boto3
from botocore.exceptions import ClientError

from kulshan.cur.s3_check import parse_s3_uri


class CurManifestError(Exception):
    """Raised when a CUR/Data Export manifest cannot be read."""


@dataclass(frozen=True)
class ManifestFile:
    """One data file referenced by a CUR/Data Export manifest."""

    s3_key: str
    size_bytes: int = 0
    row_count: int | None = None


@dataclass(frozen=True)
class ManifestIndex:
    """Resolved manifest metadata for S3-native CUR queries."""

    bucket: str
    prefix: str
    billing_period: str | None
    export_name: str | None
    files: tuple[ManifestFile, ...]
    columns: tuple[str, ...]
    total_size_bytes: int
    s3_glob: str
    manifest_key: str
    manifest_size_bytes: int


def read_manifest(
    bucket: str,
    prefix: str,
    billing_period: str | None = None,
    *,
    s3_client=None,
) -> ManifestIndex:
    """Locate and parse a CUR/Data Export manifest without reading Parquet files."""
    client = s3_client or boto3.client("s3")
    manifest_key, manifest_size = _locate_manifest(client, bucket, prefix, billing_period)
    try:
        response = client.get_object(Bucket=bucket, Key=manifest_key)
    except ClientError as exc:
        if _client_error_code(exc) in {"403", "AccessDenied", "Forbidden"}:
            raise CurManifestError(
                "Access denied reading Manifest.json with GetObject. Likely missing "
                f"s3:GetObject on arn:aws:s3:::{bucket}/{prefix.rstrip('/')}/*; "
                "kms:Decrypt may also be required for customer-managed KMS keys."
            ) from exc
        raise

    try:
        payload = response["Body"].read().decode("utf-8")
        data = json.loads(payload)
    except json.JSONDecodeError as exc:
        raise CurManifestError(
            f"Could not parse manifest JSON at s3://{bucket}/{manifest_key}."
        ) from exc

    files = _manifest_files(data, bucket)
    if not files:
        raise CurManifestError(
            f"Manifest at s3://{bucket}/{manifest_key} does not list data files."
        )
    files = _fill_missing_file_sizes(client, bucket, files)
    columns = _manifest_columns(data)
    export_name = _first_string(data, "exportName", "dataExportName", "reportName")
    period = billing_period or _first_string(data, "billingPeriod", "billing_period")
    total_size = sum(file.size_bytes for file in files)
    return ManifestIndex(
        bucket=bucket,
        prefix=prefix,
        billing_period=period,
        export_name=export_name,
        files=tuple(files),
        columns=tuple(columns),
        total_size_bytes=total_size,
        s3_glob=_s3_glob(bucket, files),
        manifest_key=manifest_key,
        manifest_size_bytes=manifest_size,
    )


def read_manifest_uri(
    s3_uri: str,
    billing_period: str | None = None,
    *,
    s3_client=None,
) -> ManifestIndex:
    """Read a manifest from an s3://bucket/prefix URI."""
    bucket, prefix = parse_s3_uri(s3_uri)
    return read_manifest(bucket, prefix, billing_period, s3_client=s3_client)


def _locate_manifest(
    client, bucket: str, prefix: str, billing_period: str | None
) -> tuple[str, int]:
    normalized = prefix.strip("/")
    candidates: list[str] = []
    if billing_period:
        candidates.append(f"{normalized}/metadata/BILLING_PERIOD={billing_period}/")
    candidates.append(f"{normalized}/metadata/")

    for search_prefix in candidates:
        try:
            response = client.list_objects_v2(
                Bucket=bucket,
                Prefix=search_prefix,
                MaxKeys=100,
            )
        except ClientError as exc:
            if _client_error_code(exc) in {"403", "AccessDenied", "Forbidden"}:
                raise CurManifestError(
                    "Access denied while locating Manifest.json. Likely missing "
                    f"s3:ListBucket on arn:aws:s3:::{bucket} with prefix {search_prefix}."
                ) from exc
            raise
        matches = [
            obj
            for obj in response.get("Contents", [])
            if str(obj.get("Key", "")).endswith("Manifest.json")
        ]
        if matches:
            first = sorted(matches, key=lambda obj: str(obj.get("Key", "")))[0]
            return str(first["Key"]), int(first.get("Size", 0) or 0)

    raise CurManifestError(
        f"Manifest.json was not found. Run: kulshan cur s3-check --s3 s3://{bucket}/{prefix}"
    )


def _manifest_files(data: dict[str, Any], bucket: str) -> list[ManifestFile]:
    raw_files = (
        data.get("dataFileS3Keys")
        or data.get("data_file_s3_keys")
        or data.get("reportKeys")
        or data.get("files")
        or data.get("dataFiles")
        or []
    )
    files: list[ManifestFile] = []
    for item in raw_files:
        key: str | None = None
        size = 0
        rows = None
        if isinstance(item, str):
            key = item
        elif isinstance(item, dict):
            key = item.get("s3Key") or item.get("key") or item.get("s3_key") or item.get("url")
            size = int(item.get("size") or item.get("sizeBytes") or item.get("size_bytes") or 0)
            if item.get("rowCount") is not None or item.get("row_count") is not None:
                rows = int(item.get("rowCount") or item.get("row_count"))
        if key:
            if key.startswith("s3://"):
                _parsed_bucket, parsed_key = parse_s3_uri(key)
                key = parsed_key
            files.append(ManifestFile(s3_key=key, size_bytes=size, row_count=rows))
    return files



def _fill_missing_file_sizes(client, bucket: str, files: list[ManifestFile]) -> list[ManifestFile]:
    sized_files: list[ManifestFile] = []
    for file in files:
        if file.size_bytes > 0:
            sized_files.append(file)
            continue
        try:
            response = client.head_object(Bucket=bucket, Key=file.s3_key)
        except ClientError:
            sized_files.append(file)
            continue
        sized_files.append(
            ManifestFile(
                s3_key=file.s3_key,
                size_bytes=int(response.get("ContentLength", 0) or 0),
                row_count=file.row_count,
            )
        )
    return sized_files
def _manifest_columns(data: dict[str, Any]) -> list[str]:
    raw_columns = data.get("columns") or data.get("schema") or data.get("columnNames") or []
    columns: list[str] = []
    for column in raw_columns:
        if isinstance(column, str):
            columns.append(column.lower())
        elif isinstance(column, dict):
            name = column.get("name") or column.get("columnName")
            if name:
                columns.append(str(name).lower())
    return columns


def _s3_glob(bucket: str, files: list[ManifestFile]) -> str:
    if len(files) == 1:
        return f"s3://{bucket}/{files[0].s3_key}"
    common = _common_prefix([file.s3_key for file in files])
    return f"s3://{bucket}/{common}*.parquet"


def _common_prefix(values: list[str]) -> str:
    if not values:
        return ""
    prefix = values[0]
    for value in values[1:]:
        while not value.startswith(prefix) and prefix:
            prefix = prefix[:-1]
    return prefix.rsplit("/", 1)[0] + "/" if "/" in prefix else prefix


def _first_string(data: dict[str, Any], *keys: str) -> str | None:
    for key in keys:
        value = data.get(key)
        if isinstance(value, str) and value:
            return value
    return None


def _client_error_code(exc: ClientError) -> str:
    return str(exc.response.get("Error", {}).get("Code", ""))
