"""Identifier-class-aware canonicalization.

Normalizes variant representations of the same AWS identity to a single
canonical string BEFORE HMAC derivation. This ensures that:
- The same identity always produces the same alias regardless of surface form.
- Superficially similar but semantically different identifiers remain distinct.

Each identifier class has its own canonicalizer. There is NO generic
strip-ARN-to-resource-ID helper.
"""
from __future__ import annotations

import re

from kulshan.pseudonym.types import IdentifierClass

# ---------------------------------------------------------------------------
# Resource ID patterns (globally unique within AWS partition)
# ---------------------------------------------------------------------------

_EC2_INSTANCE_RE = re.compile(r"^i-[0-9a-f]{8,17}$")
_EBS_VOLUME_RE = re.compile(r"^vol-[0-9a-f]{8,17}$")
_EBS_SNAPSHOT_RE = re.compile(r"^snap-[0-9a-f]{8,17}$")
_AMI_RE = re.compile(r"^ami-[0-9a-f]{8,17}$")
_ENI_RE = re.compile(r"^eni-[0-9a-f]{8,17}$")
_EIP_ALLOC_RE = re.compile(r"^eipalloc-[0-9a-f]{8,17}$")
_SP_ID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")

# ARN structure: arn:partition:service:region:account:resource
_ARN_RE = re.compile(
    r"^arn:(?P<partition>aws[^:]*):(?P<service>[^:]+):(?P<region>[^:]*)"
    r":(?P<account>[^:]*):(?P<resource>.+)$"
)

# Account ID: exactly 12 digits
_ACCOUNT_ID_RE = re.compile(r"^\d{12}$")


def canonicalize(value: str, identifier_class: IdentifierClass) -> str:
    """Produce the canonical form for an identifier given its class.

    Args:
        value: Raw identifier string.
        identifier_class: Classification of this identifier.

    Returns:
        Canonical string suitable for HMAC input.
    """
    handler = _CANONICALIZERS.get(identifier_class, _canonical_unknown)
    return handler(value)


def classify_and_canonicalize(value: str) -> tuple[IdentifierClass, str]:
    """Attempt to classify a raw value and return its canonical form.

    Used for free-text scanning where the identifier class is not known
    from field context.

    Returns:
        (IdentifierClass, canonical_form) tuple.
    """
    # Try structured patterns first
    if _ACCOUNT_ID_RE.match(value):
        return IdentifierClass.ACCOUNT, _canonical_account(value)

    arn_match = _ARN_RE.match(value)
    if arn_match:
        return _classify_arn(arn_match)

    if _EC2_INSTANCE_RE.match(value):
        return IdentifierClass.RESOURCE, _canonical_resource(value)
    if _EBS_VOLUME_RE.match(value):
        return IdentifierClass.RESOURCE, _canonical_resource(value)
    if _EBS_SNAPSHOT_RE.match(value):
        return IdentifierClass.RESOURCE, _canonical_resource(value)
    if _AMI_RE.match(value):
        return IdentifierClass.RESOURCE, _canonical_resource(value)
    if _ENI_RE.match(value):
        return IdentifierClass.RESOURCE, _canonical_resource(value)
    if _EIP_ALLOC_RE.match(value):
        return IdentifierClass.RESOURCE, _canonical_resource(value)

    return IdentifierClass.UNKNOWN, _canonical_unknown(value)


# ---------------------------------------------------------------------------
# Per-class canonicalizers
# ---------------------------------------------------------------------------


def _canonical_account(value: str) -> str:
    """Account IDs are globally unique 12-digit numbers."""
    return f"account:{value.strip()}"


def _canonical_resource(value: str) -> str:
    """EC2/EBS/ENI/EIP resource IDs are globally unique within a partition.

    Bare IDs (i-xxx, vol-xxx, etc.) and their ARN equivalents canonicalize
    to the same form because these IDs are globally unique.
    """
    return f"resource:{value.strip()}"


def _canonical_arn(value: str) -> str:
    """Generic ARN canonicalization preserving full context.

    Used for ARNs where the resource portion is NOT a globally-unique
    resource ID (e.g., Lambda function names, custom resources).
    The full service/region/account/resource-type context is needed
    to prevent cross-service collisions.
    """
    match = _ARN_RE.match(value)
    if not match:
        return f"arn:{value}"
    # Preserve full structure minus account (account is separately pseudonymized)
    service = match.group("service")
    region = match.group("region")
    resource = match.group("resource")
    return f"arn:{service}:{region}:{resource}"


def _canonical_savings_plan(value: str) -> str:
    """SP ARN -> extract SP ID (globally unique UUID)."""
    match = _ARN_RE.match(value)
    if match:
        resource = match.group("resource")
        # savingsplan/UUID
        parts = resource.split("/", 1)
        if len(parts) == 2:
            return f"sp:{parts[1]}"
    # Bare SP ID
    return f"sp:{value.strip()}"


def _canonical_reserved_instance(value: str) -> str:
    """RI ARN -> extract RI ID."""
    match = _ARN_RE.match(value)
    if match:
        resource = match.group("resource")
        # reserved-instances/ID
        parts = resource.split("/", 1)
        if len(parts) == 2:
            return f"ri:{parts[1]}"
    return f"ri:{value.strip()}"


def _canonical_invoice(value: str) -> str:
    """Invoice IDs are opaque strings."""
    return f"invoice:{value.strip()}"


def _canonical_s3_bucket(value: str) -> str:
    """S3 bucket names are globally unique DNS labels.

    Both bare name and bucket ARN canonicalize to the same form.
    """
    match = _ARN_RE.match(value)
    if match and match.group("service") == "s3":
        # arn:aws:s3:::bucket-name -> bucket-name
        resource = match.group("resource")
        return f"s3-bucket:{resource}"
    return f"s3-bucket:{value.strip()}"


def _canonical_hostname(value: str) -> str:
    """Hostnames are lowercased (DNS is case-insensitive)."""
    return f"hostname:{value.strip().lower()}"


def _canonical_email(value: str) -> str:
    """Emails are lowercased (case-insensitive per RFC 5321 local-part convention)."""
    return f"email:{value.strip().lower()}"


def _canonical_ip(value: str) -> str:
    """IP addresses are used as-is."""
    return f"ip:{value.strip()}"


def _canonical_tag_value(value: str) -> str:
    """Tag values are arbitrary strings, used as-is."""
    return f"tag-value:{value}"


def _canonical_unknown(value: str) -> str:
    """Fallback for unclassified identifiers."""
    return f"unknown:{value}"


# ---------------------------------------------------------------------------
# ARN classification
# ---------------------------------------------------------------------------

# Resource ID patterns extractable from ARN resource portion
_ARN_EXTRACTABLE_RESOURCES = {
    "instance": _EC2_INSTANCE_RE,
    "volume": _EBS_VOLUME_RE,
    "snapshot": _EBS_SNAPSHOT_RE,
    "image": _AMI_RE,
    "network-interface": _ENI_RE,
    "elastic-ip": _EIP_ALLOC_RE,
}


def _classify_arn(match: re.Match) -> tuple[IdentifierClass, str]:
    """Classify an ARN and produce its canonical form.

    For ARNs containing globally-unique resource IDs (EC2 instances, volumes,
    etc.), the canonical form uses the bare resource ID. This ensures
    consistency between bare-ID and ARN representations.

    For ARNs with account-scoped resource names (Lambda functions, etc.),
    the full ARN context is preserved to prevent collisions.
    """
    service = match.group("service")
    resource = match.group("resource")

    # S3 bucket ARNs
    if service == "s3":
        bucket_name = resource.split("/")[0]
        return IdentifierClass.S3_BUCKET, f"s3-bucket:{bucket_name}"

    # Savings Plans
    if service == "savingsplans":
        parts = resource.split("/", 1)
        if len(parts) == 2:
            return IdentifierClass.SAVINGS_PLAN, f"sp:{parts[1]}"

    # Reserved Instances
    if "reserved-instances" in resource:
        parts = resource.split("/", 1)
        if len(parts) == 2:
            return IdentifierClass.RESERVED_INSTANCE, f"ri:{parts[1]}"

    # Check for extractable globally-unique resource IDs
    parts = resource.split("/")
    if len(parts) >= 2:
        resource_type = parts[0]
        resource_id = parts[-1]
        pattern = _ARN_EXTRACTABLE_RESOURCES.get(resource_type)
        if pattern and pattern.match(resource_id):
            return IdentifierClass.RESOURCE, f"resource:{resource_id}"

    # Generic ARN: preserve full context (service + region + resource)
    region = match.group("region")
    return IdentifierClass.ARN, f"arn:{service}:{region}:{resource}"


# ---------------------------------------------------------------------------
# Canonicalizer dispatch
# ---------------------------------------------------------------------------

_CANONICALIZERS = {
    IdentifierClass.ACCOUNT: _canonical_account,
    IdentifierClass.RESOURCE: _canonical_resource,
    IdentifierClass.ARN: _canonical_arn,
    IdentifierClass.SAVINGS_PLAN: _canonical_savings_plan,
    IdentifierClass.RESERVED_INSTANCE: _canonical_reserved_instance,
    IdentifierClass.INVOICE: _canonical_invoice,
    IdentifierClass.S3_BUCKET: _canonical_s3_bucket,
    IdentifierClass.HOSTNAME: _canonical_hostname,
    IdentifierClass.EMAIL: _canonical_email,
    IdentifierClass.IP_ADDRESS: _canonical_ip,
    IdentifierClass.TAG_VALUE: _canonical_tag_value,
    IdentifierClass.UNKNOWN: _canonical_unknown,
}
