"""Field and value classification for pseudonymization.

Classifies (key, value) pairs into identifier classes or PASSTHROUGH.
Uses structural field-name rules for fast classification and pattern
matching for free-text scanning.
"""
from __future__ import annotations

import re
from enum import Enum
from typing import Optional

from kulshan.pseudonym.types import IdentifierClass


# ---------------------------------------------------------------------------
# Column classification enum (foundation for 0.6.0 CUR export)
# ---------------------------------------------------------------------------


class ColumnClassification(Enum):
    """Classification of a data column for privacy treatment."""

    PASSTHROUGH = "passthrough"
    """Value is safe: costs, dates, service names, regions, usage types."""

    PSEUDONYMIZE = "pseudonymize"
    """Value is a customer identifier: replaced with HMAC alias."""

    TRANSFORM_TAG = "transform_tag"
    """Tag value: pseudonymized by default, --keep-tag can preserve (0.6.0)."""

    DROP = "drop"
    """Value has no analytical use and contains risk: removed from export."""

    UNCLASSIFIED = "unclassified"
    """Column not in registry: blocks export in future consultant mode."""


# ---------------------------------------------------------------------------
# Field-name classification (fast path for structured output)
# ---------------------------------------------------------------------------

# Fields whose values are account IDs
_ACCOUNT_FIELDS = frozenset({
    "account_id", "account", "accountid", "payer_account_id",
    "linked_account", "payer_account", "session_account_id",
    "expected_session_account_id",
})

# Fields whose values are ARNs
_ARN_FIELDS = frozenset({
    "resource_arn", "arn", "role_arn",
})

# Fields whose values are emails
_EMAIL_FIELDS = frozenset({
    "email", "owner_hint", "contact",
})

# Fields whose values are IPs
_IP_FIELDS = frozenset({
    "ip", "ip_address", "public_ip", "private_ip",
    "source_ip", "destination_ip",
})

# Fields whose values are S3 buckets
_BUCKET_FIELDS = frozenset({
    "bucket", "bucket_name", "s3_bucket", "bucketname",
})

# Fields whose values are hostnames/endpoints
_HOST_FIELDS = frozenset({
    "host", "hostname", "endpoint", "endpoint_url",
    "domain", "domain_name", "dns_name",
})

# Fields whose values are free text that may contain embedded identifiers
_TEXT_FIELDS = frozenset({
    "title", "description", "recommended_action",
    "why_it_matters", "remediation_text", "remediation_snippet",
})

# Fields that are safe and must NOT be pseudonymized
_PASSTHROUGH_FIELDS = frozenset({
    "severity", "pack", "kind", "check_id", "service",
    "resource_type", "region", "availability_zone",
    "confidence", "effort", "risk", "result_state",
    "kulshan_version", "overall_score", "overall_grade",
    "timestamp", "date", "duration_seconds",
    "estimated_monthly_impact", "format",
})


# ---------------------------------------------------------------------------
# Value pattern detection (for free-text scanning)
# ---------------------------------------------------------------------------

_ACCOUNT_ID_RE = re.compile(r"\b(\d{12})\b")
_ARN_RE = re.compile(r"(arn:aws[a-z-]*:[a-z0-9-]+:[a-z0-9-]*:\d{12}:[^\s,\"']+)")
_EC2_INSTANCE_RE = re.compile(r"\b(i-[0-9a-f]{8,17})\b")
_EBS_VOLUME_RE = re.compile(r"\b(vol-[0-9a-f]{8,17})\b")
_EBS_SNAPSHOT_RE = re.compile(r"\b(snap-[0-9a-f]{8,17})\b")
_AMI_RE = re.compile(r"\b(ami-[0-9a-f]{8,17})\b")
_ENI_RE = re.compile(r"\b(eni-[0-9a-f]{8,17})\b")
_EIP_ALLOC_RE = re.compile(r"\b(eipalloc-[0-9a-f]{8,17})\b")
_EMAIL_RE = re.compile(r"\b([a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,})\b")
_ACCESS_KEY_RE = re.compile(r"\b(AKIA[A-Z0-9]{16})\b")
_IPV4_RE = re.compile(r"\b(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})\b")

# Ordered list: ARN first (longer matches), then shorter patterns
_FREE_TEXT_PATTERNS: list[tuple[re.Pattern, IdentifierClass]] = [
    (_ARN_RE, IdentifierClass.ARN),
    (_ACCOUNT_ID_RE, IdentifierClass.ACCOUNT),
    (_EC2_INSTANCE_RE, IdentifierClass.RESOURCE),
    (_EBS_VOLUME_RE, IdentifierClass.RESOURCE),
    (_EBS_SNAPSHOT_RE, IdentifierClass.RESOURCE),
    (_AMI_RE, IdentifierClass.RESOURCE),
    (_ENI_RE, IdentifierClass.RESOURCE),
    (_EIP_ALLOC_RE, IdentifierClass.RESOURCE),
    (_ACCESS_KEY_RE, IdentifierClass.UNKNOWN),
    (_EMAIL_RE, IdentifierClass.EMAIL),
    (_IPV4_RE, IdentifierClass.IP_ADDRESS),
]


def classify_field(key: str) -> Optional[IdentifierClass]:
    """Classify a field by its name. Returns None if passthrough or unknown.

    Returns:
        IdentifierClass if the field value should be pseudonymized as that class.
        None if the field is passthrough (safe) or unrecognized (use pattern scan).
    """
    key_lower = key.lower()

    if key_lower in _PASSTHROUGH_FIELDS:
        return None  # Explicitly safe

    if key_lower in _ACCOUNT_FIELDS:
        return IdentifierClass.ACCOUNT
    if key_lower in _ARN_FIELDS:
        return IdentifierClass.ARN
    if key_lower in _EMAIL_FIELDS:
        return IdentifierClass.EMAIL
    if key_lower in _IP_FIELDS:
        return IdentifierClass.IP_ADDRESS
    if key_lower in _BUCKET_FIELDS:
        return IdentifierClass.S3_BUCKET
    if key_lower in _HOST_FIELDS:
        return IdentifierClass.HOSTNAME

    # Text fields need free-text scanning (handled by engine)
    # Unknown fields also get scanned
    return None  # Caller should use pattern scanning


def is_text_field(key: str) -> bool:
    """Whether this field should have free-text identifier scanning applied."""
    return key.lower() in _TEXT_FIELDS


def is_passthrough_field(key: str) -> bool:
    """Whether this field is explicitly safe and should never be pseudonymized."""
    return key.lower() in _PASSTHROUGH_FIELDS


def scan_text_for_identifiers(text: str) -> list[tuple[str, IdentifierClass, int, int]]:
    """Scan free text for embedded identifiers.

    Returns list of (matched_value, identifier_class, start, end) tuples
    sorted by position (earliest first, longest match preferred).
    """
    matches: list[tuple[str, IdentifierClass, int, int]] = []
    covered: set[tuple[int, int]] = set()

    for pattern, id_class in _FREE_TEXT_PATTERNS:
        for match in pattern.finditer(text):
            start, end = match.start(1), match.end(1)
            # Skip if this span is already covered by a longer match
            if any(s <= start and end <= e for s, e in covered):
                continue
            matches.append((match.group(1), id_class, start, end))
            covered.add((start, end))

    matches.sort(key=lambda m: m[2])
    return matches
