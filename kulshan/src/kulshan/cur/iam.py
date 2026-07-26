"""Generate least-privilege read-only access for one CUR export."""

from __future__ import annotations

from typing import Any

from kulshan.cur.discovery import CurExportInfo


def detect_bucket_kms_key(session: Any, export: CurExportInfo) -> str | None:
    """Return a customer-managed default KMS key ARN/ID when discoverable."""
    try:
        response = session.client(
            "s3", region_name=export.s3_region
        ).get_bucket_encryption(Bucket=export.s3_bucket)
    except Exception:
        return None
    rules = response.get("ServerSideEncryptionConfiguration", {}).get(
        "Rules", []
    )
    for rule in rules:
        default = rule.get("ApplyServerSideEncryptionByDefault", {})
        if default.get("SSEAlgorithm") == "aws:kms":
            return default.get("KMSMasterKeyID")
    return None


def generate_cur_access_policy(
    export: CurExportInfo,
    *,
    kms_key_arn: str | None = None,
) -> dict:
    """Build an identity-policy document scoped to the export destination."""
    prefix = export.s3_prefix.strip("/")
    prefix_values = [prefix, f"{prefix}/*"] if prefix else ["*"]
    object_arn = (
        f"arn:aws:s3:::{export.s3_bucket}/{prefix}/*"
        if prefix
        else f"arn:aws:s3:::{export.s3_bucket}/*"
    )
    statements: list[dict] = [
        {
            "Sid": "KulshanCurListPrefix",
            "Effect": "Allow",
            "Action": "s3:ListBucket",
            "Resource": f"arn:aws:s3:::{export.s3_bucket}",
            "Condition": {"StringLike": {"s3:prefix": prefix_values}},
        },
        {
            "Sid": "KulshanCurReadObjects",
            "Effect": "Allow",
            "Action": "s3:GetObject",
            "Resource": object_arn,
        },
    ]
    if kms_key_arn:
        statements.append(
            {
                "Sid": "KulshanCurDecrypt",
                "Effect": "Allow",
                "Action": "kms:Decrypt",
                "Resource": kms_key_arn,
                "Condition": {
                    "StringEquals": {
                        "kms:ViaService": f"s3.{export.s3_region}.amazonaws.com"
                    }
                },
            }
        )
    return {"Version": "2012-10-17", "Statement": statements}
