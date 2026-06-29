"""Read-only S3 readiness checks for CUR/Data Export layouts."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from urllib.parse import urlparse

import boto3
from botocore.exceptions import ClientError

_BILLING_PERIOD_RE = re.compile(r"BILLING_PERIOD=(\d{4}-\d{2})")
_HEAD_DENIED_CODES = {"403", "AccessDenied", "Forbidden"}


class S3CheckError(Exception):
    """Raised when S3 readiness checks cannot complete."""

    def __init__(
        self,
        message: str,
        *,
        kind: str,
        bucket: str | None = None,
        prefix: str = "",
    ) -> None:
        super().__init__(message)
        self.kind = kind
        self.bucket = bucket
        self.prefix = prefix


@dataclass(frozen=True)
class S3ObjectProbe:
    """Metadata for one checked S3 object."""

    key: str | None = None
    readable: bool = False
    size: int | None = None
    operation: str | None = None
    error_code: str | None = None
    likely_missing_action: str | None = None
    object_arn: str | None = None
    kms_hint: str | None = None


@dataclass(frozen=True)
class S3CheckReport:
    """Summary of a read-only S3 CUR/Data Export readiness check."""

    s3_uri: str
    bucket: str
    prefix: str
    can_list_prefix: bool
    manifest_found: bool
    parquet_found: bool
    billing_periods: tuple[str, ...]
    manifest: S3ObjectProbe = field(default_factory=S3ObjectProbe)
    parquet: S3ObjectProbe = field(default_factory=S3ObjectProbe)
    total_listed_objects: int = 0
    approximate_listed_bytes: int = 0
    metadata_prefix_found: bool = False
    data_prefix_found: bool = False

    @property
    def ready_for_manual_copy(self) -> bool:
        """Whether the prefix has readable manifest and Parquet evidence."""
        return (
            self.manifest_found
            and self.parquet_found
            and self.manifest.readable
            and self.parquet.readable
        )

    @property
    def has_head_access_denial(self) -> bool:
        """Whether any located object failed a HeadObject permission check."""
        return bool(self.manifest.error_code or self.parquet.error_code)


def parse_s3_uri(s3_uri: str) -> tuple[str, str]:
    """Parse an s3://bucket/prefix URI into bucket and prefix."""
    parsed = urlparse(s3_uri)
    if parsed.scheme != "s3" or not parsed.netloc:
        raise S3CheckError(
            "S3 readiness checks require an s3://bucket/prefix path.",
            kind="invalid_s3_uri",
        )
    prefix = parsed.path.lstrip("/")
    return parsed.netloc, prefix


def check_s3_cur_layout(s3_uri: str, *, s3_client=None, max_keys: int = 50) -> S3CheckReport:
    """Check whether an S3 prefix looks readable for manual CUR Parquet copy.

    This function intentionally never calls GetObject and never downloads object bodies.
    """
    bucket, prefix = parse_s3_uri(s3_uri)
    client = s3_client or boto3.client("s3")

    try:
        response = client.list_objects_v2(Bucket=bucket, Prefix=prefix, MaxKeys=max_keys)
    except ClientError as exc:
        if _client_error_code(exc) == "AccessDenied":
            raise S3CheckError(
                "Access denied while listing S3 prefix.",
                kind="list_access_denied",
                bucket=bucket,
                prefix=prefix,
            ) from exc
        raise

    objects = response.get("Contents", [])
    keys = [obj.get("Key", "") for obj in objects]
    manifest_key = next((key for key in keys if key.endswith("Manifest.json")), None)
    parquet_key = next((key for key in keys if key.endswith(".parquet")), None)
    billing_periods = tuple(
        sorted(
            {
                match.group(1)
                for key in keys
                for match in [_BILLING_PERIOD_RE.search(key)]
                if match
            }
        )
    )
    approximate_bytes = sum(int(obj.get("Size", 0) or 0) for obj in objects)

    manifest_probe = _head_probe(client, bucket, prefix, manifest_key)
    parquet_probe = _head_probe(client, bucket, prefix, parquet_key)

    normalized_prefix = prefix.rstrip("/")
    metadata_marker = f"{normalized_prefix}/metadata/" if normalized_prefix else "metadata/"
    data_marker = f"{normalized_prefix}/data/" if normalized_prefix else "data/"

    return S3CheckReport(
        s3_uri=s3_uri,
        bucket=bucket,
        prefix=prefix,
        can_list_prefix=True,
        manifest_found=manifest_key is not None,
        parquet_found=parquet_key is not None,
        billing_periods=billing_periods,
        manifest=manifest_probe,
        parquet=parquet_probe,
        total_listed_objects=len(objects),
        approximate_listed_bytes=approximate_bytes,
        metadata_prefix_found=any(
            metadata_marker in key or key.endswith("metadata/") for key in keys
        ),
        data_prefix_found=any(data_marker in key or key.endswith("data/") for key in keys),
    )


def _head_probe(
    client,
    bucket: str,
    prefix: str,
    key: str | None,
) -> S3ObjectProbe:
    if key is None:
        return S3ObjectProbe()
    try:
        response = client.head_object(Bucket=bucket, Key=key)
    except ClientError as exc:
        error_code = _client_error_code(exc)
        if error_code in _HEAD_DENIED_CODES:
            return S3ObjectProbe(
                key=key,
                readable=False,
                operation="HeadObject",
                error_code=error_code,
                likely_missing_action="s3:GetObject",
                object_arn=_prefix_object_arn(bucket, prefix),
                kms_hint=(
                    "kms:Decrypt may also be needed if the bucket or object uses a "
                    "customer-managed KMS key."
                ),
            )
        raise
    return S3ObjectProbe(key=key, readable=True, size=response.get("ContentLength"))


def _prefix_object_arn(bucket: str, prefix: str) -> str:
    normalized_prefix = prefix.rstrip("/")
    if normalized_prefix:
        return f"arn:aws:s3:::{bucket}/{normalized_prefix}/*"
    return f"arn:aws:s3:::{bucket}/*"


def _client_error_code(exc: ClientError) -> str:
    return str(exc.response.get("Error", {}).get("Code", ""))
