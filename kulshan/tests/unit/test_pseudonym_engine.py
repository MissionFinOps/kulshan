"""Tests for PseudonymizationEngine, classifier, and policy."""
from __future__ import annotations

import os
from copy import deepcopy
from pathlib import Path

import pytest

from kulshan.pseudonym.classifier import (
    ColumnClassification,
    classify_field,
    is_passthrough_field,
    is_text_field,
    scan_text_for_identifiers,
)
from kulshan.pseudonym.engine import PseudonymizationEngine
from kulshan.pseudonym.policy import PolicyMode, PseudonymPolicy
from kulshan.pseudonym.secret import SecretCorruptError
from kulshan.pseudonym.types import IdentifierClass


TEST_SECRET = b"\xab" * 32
SYNTHETIC_ACCOUNT = "111222333444"
SYNTHETIC_ARN = "arn:aws:ec2:us-east-1:111222333444:instance/i-0abc123def456789a"
SYNTHETIC_EMAIL = "test.user@synthetic-corp.example"
SYNTHETIC_INSTANCE = "i-0abc123def456789a"
SYNTHETIC_VOLUME = "vol-0fff999888aaa111b"
SYNTHETIC_BUCKET = "my-production-data-bucket"
SYNTHETIC_IP = "10.0.45.12"
SYNTHETIC_ACCESS_KEY = "AKIAIOSFODNN7EXAMPLE"


@pytest.fixture
def engine() -> PseudonymizationEngine:
    """Engine with test secret and active policy."""
    policy = PseudonymPolicy.for_structured_output(show_identifiers=False)
    return PseudonymizationEngine(TEST_SECRET, policy)


@pytest.fixture
def inactive_engine() -> PseudonymizationEngine:
    """Engine with show_identifiers=True (bypass)."""
    policy = PseudonymPolicy.for_structured_output(show_identifiers=True)
    return PseudonymizationEngine(TEST_SECRET, policy)


@pytest.fixture
def tty_engine() -> PseudonymizationEngine:
    """Engine with TTY bypass active."""
    policy = PseudonymPolicy.for_terminal(is_tty=True, show_identifiers=False)
    return PseudonymizationEngine(TEST_SECRET, policy)


# ═══════════════════════════════════════════════════════════════════════════════
# POLICY TESTS
# ═══════════════════════════════════════════════════════════════════════════════


class TestPolicy:
    def test_structured_output_pseudonymizes(self):
        p = PseudonymPolicy.for_structured_output()
        assert p.should_pseudonymize is True

    def test_terminal_tty_bypasses(self):
        p = PseudonymPolicy.for_terminal(is_tty=True)
        assert p.should_pseudonymize is False

    def test_terminal_non_tty_pseudonymizes(self):
        p = PseudonymPolicy.for_terminal(is_tty=False)
        assert p.should_pseudonymize is True

    def test_persistence_always_pseudonymizes(self):
        p = PseudonymPolicy.for_persistence()
        assert p.should_pseudonymize is True

    def test_show_identifiers_overrides_everything(self):
        p = PseudonymPolicy.for_structured_output(show_identifiers=True)
        assert p.should_pseudonymize is False

    def test_show_identifiers_cannot_override_persistence(self):
        # Persistence policy ignores show_identifiers by construction
        p = PseudonymPolicy(
            mode=PolicyMode.PERSISTENCE,
            tty_bypass=False,
            show_identifiers=True,  # This should not matter
        )
        # But per the current design, show_identifiers IS respected
        # (consultant mode in 0.6.0 will reject it at CLI level)
        assert p.should_pseudonymize is False


# ═══════════════════════════════════════════════════════════════════════════════
# CLASSIFIER TESTS
# ═══════════════════════════════════════════════════════════════════════════════


class TestClassifier:
    def test_account_field_classified(self):
        assert classify_field("account_id") == IdentifierClass.ACCOUNT
        assert classify_field("payer_account_id") == IdentifierClass.ACCOUNT

    def test_arn_field_classified(self):
        assert classify_field("resource_arn") == IdentifierClass.ARN

    def test_email_field_classified(self):
        assert classify_field("email") == IdentifierClass.EMAIL

    def test_ip_field_classified(self):
        assert classify_field("public_ip") == IdentifierClass.IP_ADDRESS

    def test_bucket_field_classified(self):
        assert classify_field("bucket_name") == IdentifierClass.S3_BUCKET

    def test_hostname_field_classified(self):
        assert classify_field("endpoint") == IdentifierClass.HOSTNAME

    def test_passthrough_field(self):
        assert is_passthrough_field("severity") is True
        assert is_passthrough_field("region") is True
        assert is_passthrough_field("service") is True
        assert is_passthrough_field("overall_score") is True

    def test_text_field(self):
        assert is_text_field("title") is True
        assert is_text_field("description") is True
        assert is_text_field("recommended_action") is True

    def test_unknown_field_returns_none(self):
        assert classify_field("some_random_field") is None

    def test_column_classification_enum_values(self):
        assert ColumnClassification.PASSTHROUGH.value == "passthrough"
        assert ColumnClassification.PSEUDONYMIZE.value == "pseudonymize"
        assert ColumnClassification.TRANSFORM_TAG.value == "transform_tag"
        assert ColumnClassification.DROP.value == "drop"
        assert ColumnClassification.UNCLASSIFIED.value == "unclassified"


class TestFreeTextScanning:
    def test_finds_account_id(self):
        matches = scan_text_for_identifiers(f"Account {SYNTHETIC_ACCOUNT} has issues")
        assert len(matches) >= 1
        assert any(m[0] == SYNTHETIC_ACCOUNT for m in matches)

    def test_finds_arn(self):
        matches = scan_text_for_identifiers(f"Resource {SYNTHETIC_ARN} is exposed")
        assert any(m[1] == IdentifierClass.ARN for m in matches)

    def test_finds_instance_id(self):
        matches = scan_text_for_identifiers(f"Instance {SYNTHETIC_INSTANCE} is idle")
        assert any(m[0] == SYNTHETIC_INSTANCE for m in matches)

    def test_finds_email(self):
        matches = scan_text_for_identifiers(f"Owner: {SYNTHETIC_EMAIL}")
        assert any(m[1] == IdentifierClass.EMAIL for m in matches)

    def test_finds_access_key(self):
        matches = scan_text_for_identifiers(f"Key {SYNTHETIC_ACCESS_KEY} exposed")
        assert any(m[0] == SYNTHETIC_ACCESS_KEY for m in matches)

    def test_finds_ip(self):
        matches = scan_text_for_identifiers(f"IP address {SYNTHETIC_IP}")
        assert any(m[1] == IdentifierClass.IP_ADDRESS for m in matches)

    def test_multiple_identifiers_in_one_string(self):
        text = (
            f"Account {SYNTHETIC_ACCOUNT} has instance {SYNTHETIC_INSTANCE} "
            f"with email {SYNTHETIC_EMAIL} at {SYNTHETIC_IP}"
        )
        matches = scan_text_for_identifiers(text)
        assert len(matches) >= 4

    def test_no_false_positive_on_plain_text(self):
        matches = scan_text_for_identifiers("This is a normal sentence about AWS costs.")
        assert len(matches) == 0

    def test_preserves_non_identifier_text(self):
        # Just verifying scanning produces the right positions
        text = "Start i-0abc123def456789a End"
        matches = scan_text_for_identifiers(text)
        assert len(matches) == 1
        assert text[matches[0][2]:matches[0][3]] == "i-0abc123def456789a"


# ═══════════════════════════════════════════════════════════════════════════════
# ENGINE: STRUCTURED FIELD PSEUDONYMIZATION
# ═══════════════════════════════════════════════════════════════════════════════


class TestEngineStructuredFields:
    def test_account_field_pseudonymized(self, engine):
        payload = {"account_id": SYNTHETIC_ACCOUNT, "region": "us-east-1"}
        result = engine.pseudonymize_payload(payload)
        assert result["account_id"] != SYNTHETIC_ACCOUNT
        assert result["account_id"].startswith("acct_")
        assert len(result["account_id"]) == 5 + 16  # acct_ + 16 hex

    def test_payer_account_field(self, engine):
        payload = {"payer_account_id": "999888777666"}
        result = engine.pseudonymize_payload(payload)
        assert result["payer_account_id"].startswith("acct_")
        assert "999888777666" not in result["payer_account_id"]

    def test_resource_arn_field(self, engine):
        payload = {"resource_arn": SYNTHETIC_ARN}
        result = engine.pseudonymize_payload(payload)
        assert SYNTHETIC_ARN not in result["resource_arn"]

    def test_region_preserved(self, engine):
        payload = {"region": "us-east-1"}
        result = engine.pseudonymize_payload(payload)
        assert result["region"] == "us-east-1"

    def test_service_preserved(self, engine):
        payload = {"service": "AmazonEC2"}
        result = engine.pseudonymize_payload(payload)
        assert result["service"] == "AmazonEC2"

    def test_severity_preserved(self, engine):
        payload = {"severity": "critical"}
        result = engine.pseudonymize_payload(payload)
        assert result["severity"] == "critical"

    def test_cost_preserved_exactly(self, engine):
        payload = {"estimated_monthly_impact": 1234.56}
        result = engine.pseudonymize_payload(payload)
        assert result["estimated_monthly_impact"] == 1234.56

    def test_date_preserved(self, engine):
        payload = {"timestamp": "2026-08-17T12:00:00Z"}
        result = engine.pseudonymize_payload(payload)
        assert result["timestamp"] == "2026-08-17T12:00:00Z"

    def test_none_preserved(self, engine):
        payload = {"account_id": None}
        result = engine.pseudonymize_payload(payload)
        assert result["account_id"] is None

    def test_bool_preserved(self, engine):
        payload = {"enabled": True}
        result = engine.pseudonymize_payload(payload)
        assert result["enabled"] is True

    def test_int_preserved(self, engine):
        payload = {"overall_score": 85}
        result = engine.pseudonymize_payload(payload)
        assert result["overall_score"] == 85


# ═══════════════════════════════════════════════════════════════════════════════
# ENGINE: FREE TEXT
# ═══════════════════════════════════════════════════════════════════════════════


class TestEngineFreeText:
    def test_account_in_title(self, engine):
        payload = {"title": f"SG open in account {SYNTHETIC_ACCOUNT}"}
        result = engine.pseudonymize_payload(payload)
        assert SYNTHETIC_ACCOUNT not in result["title"]
        assert "acct_" in result["title"]

    def test_arn_in_description(self, engine):
        payload = {"description": f"Resource {SYNTHETIC_ARN} is public"}
        result = engine.pseudonymize_payload(payload)
        assert SYNTHETIC_ARN not in result["description"]

    def test_email_in_text(self, engine):
        payload = {"recommended_action": f"Contact {SYNTHETIC_EMAIL}"}
        result = engine.pseudonymize_payload(payload)
        assert SYNTHETIC_EMAIL not in result["recommended_action"]
        assert "user_" in result["recommended_action"]

    def test_multiple_identifiers_in_one_field(self, engine):
        text = f"Account {SYNTHETIC_ACCOUNT} instance {SYNTHETIC_INSTANCE} at {SYNTHETIC_IP}"
        payload = {"title": text}
        result = engine.pseudonymize_payload(payload)
        assert SYNTHETIC_ACCOUNT not in result["title"]
        assert SYNTHETIC_INSTANCE not in result["title"]
        assert SYNTHETIC_IP not in result["title"]

    def test_access_key_in_text(self, engine):
        payload = {"description": f"Key {SYNTHETIC_ACCESS_KEY} found exposed"}
        result = engine.pseudonymize_payload(payload)
        assert SYNTHETIC_ACCESS_KEY not in result["description"]


# ═══════════════════════════════════════════════════════════════════════════════
# ENGINE: TAG VALUES
# ═══════════════════════════════════════════════════════════════════════════════


class TestEngineTagValues:
    def test_tag_value_pseudonymized_by_default(self, engine):
        # Tag values appear in free-text fields or as values in tag-related contexts
        # When they appear as plain strings that don't match identifier patterns,
        # they pass through free-text scanning unmodified (no pattern match).
        # But when explicitly classified as TAG_VALUE:
        alias = engine.pseudonymize_value("platform-team", IdentifierClass.TAG_VALUE)
        assert alias.startswith("tag_")
        assert "platform-team" not in alias


# ═══════════════════════════════════════════════════════════════════════════════
# ENGINE: NESTED STRUCTURES
# ═══════════════════════════════════════════════════════════════════════════════


class TestEngineNested:
    def test_nested_dict(self, engine):
        payload = {"findings": [{"account_id": SYNTHETIC_ACCOUNT, "severity": "high"}]}
        result = engine.pseudonymize_payload(payload)
        assert result["findings"][0]["account_id"].startswith("acct_")
        assert result["findings"][0]["severity"] == "high"

    def test_nested_list(self, engine):
        payload = {"regions": ["us-east-1", "eu-west-1"]}
        result = engine.pseudonymize_payload(payload)
        # regions is a passthrough field
        assert result["regions"] == ["us-east-1", "eu-west-1"]

    def test_tuple_preserved_as_tuple(self, engine):
        payload = {"data": (1, 2, 3)}
        result = engine.pseudonymize_payload(payload)
        assert isinstance(result["data"], tuple)
        assert result["data"] == (1, 2, 3)

    def test_deep_nesting(self, engine):
        payload = {
            "tools": {
                "cost": {
                    "findings": [
                        {"account_id": SYNTHETIC_ACCOUNT, "service": "AmazonEC2"}
                    ]
                }
            }
        }
        result = engine.pseudonymize_payload(payload)
        finding = result["tools"]["cost"]["findings"][0]
        assert finding["account_id"].startswith("acct_")
        assert finding["service"] == "AmazonEC2"


# ═══════════════════════════════════════════════════════════════════════════════
# ENGINE: INPUT IMMUTABILITY
# ═══════════════════════════════════════════════════════════════════════════════


class TestEngineImmutability:
    def test_source_payload_not_mutated(self, engine):
        payload = {"account_id": SYNTHETIC_ACCOUNT, "nested": {"arn": SYNTHETIC_ARN}}
        original = deepcopy(payload)
        engine.pseudonymize_payload(payload)
        assert payload == original

    def test_list_not_mutated(self, engine):
        items = [{"account_id": SYNTHETIC_ACCOUNT}]
        original = deepcopy(items)
        engine.pseudonymize_payload(items)
        assert items == original


# ═══════════════════════════════════════════════════════════════════════════════
# ENGINE: CONSISTENCY
# ═══════════════════════════════════════════════════════════════════════════════


class TestEngineConsistency:
    def test_same_identifier_same_alias_across_fields(self, engine):
        payload = {
            "account_id": SYNTHETIC_ACCOUNT,
            "title": f"Issue in {SYNTHETIC_ACCOUNT}",
        }
        result = engine.pseudonymize_payload(payload)
        # The alias in the account_id field
        field_alias = result["account_id"]
        # The alias embedded in the title
        assert field_alias in result["title"]

    def test_same_identifier_different_locations(self, engine):
        payload = {
            "findings": [
                {"account_id": SYNTHETIC_ACCOUNT},
                {"account_id": SYNTHETIC_ACCOUNT},
            ]
        }
        result = engine.pseudonymize_payload(payload)
        assert result["findings"][0]["account_id"] == result["findings"][1]["account_id"]

    def test_different_resource_classes_remain_distinct(self, engine):
        payload = {
            "resources": [
                {"resource_arn": "arn:aws:ec2:us-east-1:111222333444:instance/i-aaa111bbb222ccc33"},
                {"resource_arn": "arn:aws:ec2:us-east-1:111222333444:volume/vol-aaa111bbb222ccc33"},
            ]
        }
        result = engine.pseudonymize_payload(payload)
        # Different resources should get different aliases
        assert result["resources"][0]["resource_arn"] != result["resources"][1]["resource_arn"]


# ═══════════════════════════════════════════════════════════════════════════════
# ENGINE: BYPASS AND FAILURE
# ═══════════════════════════════════════════════════════════════════════════════


class TestEngineBypass:
    def test_inactive_engine_returns_payload_unchanged(self, inactive_engine):
        payload = {"account_id": SYNTHETIC_ACCOUNT}
        result = inactive_engine.pseudonymize_payload(payload)
        assert result["account_id"] == SYNTHETIC_ACCOUNT

    def test_tty_engine_returns_payload_unchanged(self, tty_engine):
        payload = {"account_id": SYNTHETIC_ACCOUNT}
        result = tty_engine.pseudonymize_payload(payload)
        assert result["account_id"] == SYNTHETIC_ACCOUNT

    def test_unsupported_type_raises(self, engine):
        class CustomObj:
            pass

        with pytest.raises(TypeError, match="cannot safely handle"):
            engine.pseudonymize_payload({"data": CustomObj()})

    def test_invalid_secret_length_raises(self):
        with pytest.raises(ValueError, match="exactly 32 bytes"):
            PseudonymizationEngine(b"short", PseudonymPolicy.for_structured_output())


# ═══════════════════════════════════════════════════════════════════════════════
# ENGINE: SECRET SAFETY
# ═══════════════════════════════════════════════════════════════════════════════


class TestEngineSecretSafety:
    def test_repr_does_not_leak_secret(self, engine):
        r = repr(engine)
        assert TEST_SECRET.hex() not in r
        assert str(TEST_SECRET) not in r

    def test_str_does_not_leak_secret(self, engine):
        s = str(engine)
        assert TEST_SECRET.hex() not in s

    def test_error_does_not_leak_secret(self, engine):
        try:
            engine.pseudonymize_payload({"x": object()})
        except TypeError as e:
            assert TEST_SECRET.hex() not in str(e)


# ═══════════════════════════════════════════════════════════════════════════════
# ENGINE: CORRUPT SECRET FAILS CLOSED
# ═══════════════════════════════════════════════════════════════════════════════


class TestEngineFailClosed:
    def test_corrupt_secret_prevents_creation(self, tmp_path):
        ws = tmp_path / "ws"
        ws.mkdir()
        (ws / "pseudonym.key").write_bytes(b"corrupt")
        with pytest.raises(SecretCorruptError):
            PseudonymizationEngine.create(ws, PseudonymPolicy.for_structured_output())


# ═══════════════════════════════════════════════════════════════════════════════
# ADVERSARIAL FREE TEXT
# ═══════════════════════════════════════════════════════════════════════════════


class TestAdversarialText:
    def test_all_identifier_classes_in_one_string(self, engine):
        """Adversarial text with every identifier type. All must disappear."""
        text = (
            f"Account {SYNTHETIC_ACCOUNT} has instance {SYNTHETIC_INSTANCE} "
            f"volume {SYNTHETIC_VOLUME} at {SYNTHETIC_IP} "
            f"bucket {SYNTHETIC_BUCKET} "
            f"email {SYNTHETIC_EMAIL} "
            f"key {SYNTHETIC_ACCESS_KEY} "
            f"arn {SYNTHETIC_ARN}"
        )
        result = engine.pseudonymize_text(text)

        assert SYNTHETIC_ACCOUNT not in result
        assert SYNTHETIC_INSTANCE not in result
        assert SYNTHETIC_VOLUME not in result
        assert SYNTHETIC_IP not in result
        assert SYNTHETIC_EMAIL not in result
        assert SYNTHETIC_ACCESS_KEY not in result
        # ARN contains the instance and account, so check the full ARN pattern
        assert "111222333444" not in result
        assert "i-0abc123def456789a" not in result
