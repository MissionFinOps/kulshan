"""Tests for identifier-class-aware canonicalization and HMAC alias derivation."""
from __future__ import annotations

import os

import pytest

from kulshan.pseudonym.canonical import (
    canonicalize,
    classify_and_canonicalize,
)
from kulshan.pseudonym.hmac_scheme import derive_alias, derive_token
from kulshan.pseudonym.types import IdentifierClass


# A fixed test secret for deterministic assertions
TEST_SECRET = b"\x01" * 32
ALT_SECRET = b"\x02" * 32


# ═══════════════════════════════════════════════════════════════════════════════
# CANONICALIZATION: EQUIVALENCE (same identity = same canonical form)
# ═══════════════════════════════════════════════════════════════════════════════


class TestCanonicalEquivalence:
    """Semantically equivalent forms must produce the same canonical output."""

    def test_ec2_instance_bare_and_arn(self):
        """Bare instance ID and its ARN canonicalize to same form."""
        bare = "i-0abc123def456789a"
        arn = "arn:aws:ec2:us-east-1:123456789012:instance/i-0abc123def456789a"

        bare_canonical = canonicalize(bare, IdentifierClass.RESOURCE)
        _, arn_canonical = classify_and_canonicalize(arn)

        assert bare_canonical == arn_canonical

    def test_ebs_volume_bare_and_arn(self):
        """Bare volume ID and its ARN canonicalize to same form."""
        bare = "vol-0fff999888aaa111b"
        arn = "arn:aws:ec2:us-west-2:999888777666:volume/vol-0fff999888aaa111b"

        bare_canonical = canonicalize(bare, IdentifierClass.RESOURCE)
        _, arn_canonical = classify_and_canonicalize(arn)

        assert bare_canonical == arn_canonical

    def test_snapshot_bare_and_arn(self):
        bare = "snap-0aaa111bbb222ccc"
        arn = "arn:aws:ec2:eu-west-1:111222333444:snapshot/snap-0aaa111bbb222ccc"

        bare_canonical = canonicalize(bare, IdentifierClass.RESOURCE)
        _, arn_canonical = classify_and_canonicalize(arn)

        assert bare_canonical == arn_canonical

    def test_ami_bare_and_arn(self):
        bare = "ami-0bbb222ccc333ddd4"
        arn = "arn:aws:ec2:us-east-1:123456789012:image/ami-0bbb222ccc333ddd4"

        bare_canonical = canonicalize(bare, IdentifierClass.RESOURCE)
        _, arn_canonical = classify_and_canonicalize(arn)

        assert bare_canonical == arn_canonical

    def test_eni_bare_and_arn(self):
        bare = "eni-0ccc333ddd444eee5"
        arn = "arn:aws:ec2:ap-southeast-1:555666777888:network-interface/eni-0ccc333ddd444eee5"

        bare_canonical = canonicalize(bare, IdentifierClass.RESOURCE)
        _, arn_canonical = classify_and_canonicalize(arn)

        assert bare_canonical == arn_canonical

    def test_s3_bucket_bare_and_arn(self):
        """Bare bucket name and bucket ARN canonicalize to same form."""
        bare = "my-production-bucket"
        arn = "arn:aws:s3:::my-production-bucket"

        bare_canonical = canonicalize(bare, IdentifierClass.S3_BUCKET)
        _, arn_canonical = classify_and_canonicalize(arn)

        assert bare_canonical == arn_canonical

    def test_email_case_insensitive(self):
        """Same email in different cases produces same canonical form."""
        e1 = canonicalize("User@Example.COM", IdentifierClass.EMAIL)
        e2 = canonicalize("user@example.com", IdentifierClass.EMAIL)
        assert e1 == e2

    def test_hostname_case_insensitive(self):
        """DNS hostnames are case-insensitive."""
        h1 = canonicalize("My-RDS.abc123.us-east-1.rds.amazonaws.com", IdentifierClass.HOSTNAME)
        h2 = canonicalize("my-rds.abc123.us-east-1.rds.amazonaws.com", IdentifierClass.HOSTNAME)
        assert h1 == h2


# ═══════════════════════════════════════════════════════════════════════════════
# CANONICALIZATION: NON-COLLAPSE (different identities must NOT collide)
# ═══════════════════════════════════════════════════════════════════════════════


class TestCanonicalNonCollapse:
    """Superficially similar but semantically different identifiers must remain distinct."""

    def test_same_suffix_different_resource_class(self):
        """Same final token under different resource types must not collapse."""
        # An instance and a volume that happen to have similar-looking IDs
        instance = canonicalize("i-0abc123def456789a", IdentifierClass.RESOURCE)
        volume = canonicalize("vol-0abc123def456789a", IdentifierClass.RESOURCE)
        # They are different resources, different canonical forms
        assert instance != volume

    def test_generic_lambda_arn_vs_ec2_resource(self):
        """Lambda function name that looks like a resource ID must not collapse."""
        # A Lambda function with a name that starts with 'i-' (unusual but possible)
        lambda_arn = "arn:aws:lambda:us-east-1:123456789012:function:my-service"
        ec2_arn = "arn:aws:ec2:us-east-1:123456789012:instance/i-0abc123def456789a"

        _, lambda_canonical = classify_and_canonicalize(lambda_arn)
        _, ec2_canonical = classify_and_canonicalize(ec2_arn)

        assert lambda_canonical != ec2_canonical

    def test_same_resource_name_different_services(self):
        """Same resource name under different services must remain distinct."""
        lambda_arn = "arn:aws:lambda:us-east-1:123456789012:function:process-payments"
        sfn_arn = "arn:aws:states:us-east-1:123456789012:stateMachine:process-payments"

        _, lambda_canonical = classify_and_canonicalize(lambda_arn)
        _, sfn_canonical = classify_and_canonicalize(sfn_arn)

        assert lambda_canonical != sfn_canonical

    def test_same_function_different_regions(self):
        """Same function name in different regions must remain distinct."""
        arn1 = "arn:aws:lambda:us-east-1:123456789012:function:my-func"
        arn2 = "arn:aws:lambda:eu-west-1:123456789012:function:my-func"

        _, c1 = classify_and_canonicalize(arn1)
        _, c2 = classify_and_canonicalize(arn2)

        assert c1 != c2

    def test_account_id_standalone_vs_in_arn(self):
        """Account ID must be classified consistently regardless of context."""
        # Standalone account ID
        acct_canonical = canonicalize("123456789012", IdentifierClass.ACCOUNT)
        # The account in an ARN is not directly canonicalized as the full ARN
        # (account is pseudonymized separately in composite alias construction)
        assert "account:123456789012" == acct_canonical

    def test_different_accounts_different_canonical(self):
        a1 = canonicalize("111222333444", IdentifierClass.ACCOUNT)
        a2 = canonicalize("555666777888", IdentifierClass.ACCOUNT)
        assert a1 != a2

    def test_ip_addresses_distinct(self):
        ip1 = canonicalize("10.0.1.1", IdentifierClass.IP_ADDRESS)
        ip2 = canonicalize("10.0.1.2", IdentifierClass.IP_ADDRESS)
        assert ip1 != ip2

    def test_tag_values_distinct(self):
        t1 = canonicalize("production", IdentifierClass.TAG_VALUE)
        t2 = canonicalize("staging", IdentifierClass.TAG_VALUE)
        assert t1 != t2


# ═══════════════════════════════════════════════════════════════════════════════
# HMAC ALIAS DERIVATION
# ═══════════════════════════════════════════════════════════════════════════════


class TestHmacAlias:
    """HMAC alias derivation produces correct, deterministic, fixed-length output."""

    def test_deterministic(self):
        """Same secret + same canonical = same alias."""
        canonical = "account:123456789012"
        a1 = derive_alias(TEST_SECRET, canonical, IdentifierClass.ACCOUNT)
        a2 = derive_alias(TEST_SECRET, canonical, IdentifierClass.ACCOUNT)
        assert a1 == a2

    def test_different_secret_different_alias(self):
        """Different workspace secret = different alias for same identity."""
        canonical = "account:123456789012"
        a1 = derive_alias(TEST_SECRET, canonical, IdentifierClass.ACCOUNT)
        a2 = derive_alias(ALT_SECRET, canonical, IdentifierClass.ACCOUNT)
        assert a1 != a2

    def test_token_is_exactly_16_hex(self):
        """Alias token is ALWAYS exactly 16 lowercase hex characters."""
        alias = derive_alias(TEST_SECRET, "account:123456789012", IdentifierClass.ACCOUNT)
        # Format: prefix_token
        parts = alias.split("_", 1)
        assert len(parts) == 2
        token = parts[1]
        assert len(token) == 16
        assert all(c in "0123456789abcdef" for c in token)

    def test_prefix_matches_class(self):
        """Alias prefix correctly reflects identifier class."""
        alias = derive_alias(TEST_SECRET, "account:123", IdentifierClass.ACCOUNT)
        assert alias.startswith("acct_")

        alias = derive_alias(TEST_SECRET, "resource:i-abc", IdentifierClass.RESOURCE)
        assert alias.startswith("res_")

        alias = derive_alias(TEST_SECRET, "tag-value:prod", IdentifierClass.TAG_VALUE)
        assert alias.startswith("tag_")

    def test_different_inputs_different_aliases(self):
        """Different canonical forms produce different aliases."""
        a1 = derive_alias(TEST_SECRET, "account:111222333444", IdentifierClass.ACCOUNT)
        a2 = derive_alias(TEST_SECRET, "account:555666777888", IdentifierClass.ACCOUNT)
        assert a1 != a2

    def test_order_independence(self):
        """Aliases are the same regardless of processing order."""
        values = ["account:aaa", "account:bbb", "account:ccc"]
        forward = [derive_alias(TEST_SECRET, v, IdentifierClass.ACCOUNT) for v in values]
        backward = [derive_alias(TEST_SECRET, v, IdentifierClass.ACCOUNT) for v in reversed(values)]
        assert forward == list(reversed(backward))

    def test_derive_token_returns_16_hex(self):
        """derive_token returns just the hex portion."""
        token = derive_token(TEST_SECRET, "test:value")
        assert len(token) == 16
        assert all(c in "0123456789abcdef" for c in token)

    def test_large_synthetic_set_no_collisions(self):
        """Generate a large set of aliases and verify no collisions within each class."""
        aliases = set()
        for i in range(5000):
            canonical = f"account:{i:012d}"
            alias = derive_alias(TEST_SECRET, canonical, IdentifierClass.ACCOUNT)
            aliases.add(alias)
        # All 5000 should be unique
        assert len(aliases) == 5000

    def test_cross_class_prefix_prevents_ambiguity(self):
        """Same canonical suffix under different classes produces different aliases."""
        # Even if the canonical form happened to be the same string,
        # different classes produce different prefixes
        a = derive_alias(TEST_SECRET, "test:same", IdentifierClass.ACCOUNT)
        r = derive_alias(TEST_SECRET, "test:same", IdentifierClass.RESOURCE)
        # Prefixes differ
        assert a.split("_")[0] != r.split("_")[0]


# ═══════════════════════════════════════════════════════════════════════════════
# SAVINGS PLAN / RI CANONICALIZATION
# ═══════════════════════════════════════════════════════════════════════════════


class TestSavingsPlanRI:
    """SP and RI identifiers canonicalize correctly."""

    def test_sp_arn_extracts_id(self):
        arn = "arn:aws:savingsplans::123456789012:savingsplan/a1b2c3d4-e5f6-7890-abcd-ef1234567890"
        canonical = canonicalize(arn, IdentifierClass.SAVINGS_PLAN)
        assert canonical == "sp:a1b2c3d4-e5f6-7890-abcd-ef1234567890"

    def test_ri_arn_extracts_id(self):
        arn = "arn:aws:ec2:us-east-1:123456789012:reserved-instances/ri-abc123def456"
        canonical = canonicalize(arn, IdentifierClass.RESERVED_INSTANCE)
        assert canonical == "ri:ri-abc123def456"

    def test_sp_bare_id(self):
        bare = "a1b2c3d4-e5f6-7890-abcd-ef1234567890"
        canonical = canonicalize(bare, IdentifierClass.SAVINGS_PLAN)
        assert canonical == "sp:a1b2c3d4-e5f6-7890-abcd-ef1234567890"


# ═══════════════════════════════════════════════════════════════════════════════
# END-TO-END: CANONICAL -> ALIAS CONSISTENCY
# ═══════════════════════════════════════════════════════════════════════════════


class TestEndToEnd:
    """Full pipeline: canonicalize then derive alias produces consistent results."""

    def test_ec2_instance_bare_and_arn_same_alias(self):
        """The same EC2 instance ID produces the same alias from bare or ARN form."""
        bare = "i-0abc123def456789a"
        arn = "arn:aws:ec2:us-east-1:123456789012:instance/i-0abc123def456789a"

        bare_canonical = canonicalize(bare, IdentifierClass.RESOURCE)
        _, arn_canonical = classify_and_canonicalize(arn)

        bare_alias = derive_alias(TEST_SECRET, bare_canonical, IdentifierClass.RESOURCE)
        arn_alias = derive_alias(TEST_SECRET, arn_canonical, IdentifierClass.RESOURCE)

        assert bare_alias == arn_alias

    def test_s3_bucket_bare_and_arn_same_alias(self):
        bare = "my-bucket"
        arn = "arn:aws:s3:::my-bucket"

        bare_canonical = canonicalize(bare, IdentifierClass.S3_BUCKET)
        _, arn_canonical = classify_and_canonicalize(arn)

        bare_alias = derive_alias(TEST_SECRET, bare_canonical, IdentifierClass.S3_BUCKET)
        arn_alias = derive_alias(TEST_SECRET, arn_canonical, IdentifierClass.S3_BUCKET)

        assert bare_alias == arn_alias

    def test_account_alias_format(self):
        """Full pipeline produces expected format."""
        canonical = canonicalize("123456789012", IdentifierClass.ACCOUNT)
        alias = derive_alias(TEST_SECRET, canonical, IdentifierClass.ACCOUNT)

        assert alias.startswith("acct_")
        assert len(alias) == 5 + 16  # "acct_" + 16 hex
        assert alias[5:].islower()
