"""Tests for pseudonymization types: SensitiveId and IdentifierClass."""
from __future__ import annotations

import pytest

from kulshan.pseudonym.types import IdentifierClass, SensitiveId


class TestSensitiveId:
    """SensitiveId must never expose raw value through str/repr."""

    def test_str_masks_value(self):
        sid = SensitiveId("123456789012")
        assert "123456789012" not in str(sid)
        assert str(sid) == "***9012"

    def test_str_short_value(self):
        sid = SensitiveId("ab")
        assert str(sid) == "***"

    def test_str_empty(self):
        sid = SensitiveId("")
        assert str(sid) == "***"

    def test_repr_does_not_leak(self):
        sid = SensitiveId("secret-account-123456789012")
        assert "secret-account" not in repr(sid)
        assert "SensitiveId(" in repr(sid)

    def test_raw_returns_original(self):
        sid = SensitiveId("123456789012")
        assert sid.raw == "123456789012"

    def test_equality_with_same_raw(self):
        a = SensitiveId("123456789012")
        b = SensitiveId("123456789012")
        assert a == b

    def test_equality_with_different_raw(self):
        a = SensitiveId("111222333444")
        b = SensitiveId("555666777888")
        assert a != b

    def test_equality_with_str(self):
        sid = SensitiveId("hello")
        assert sid == "hello"
        assert sid != "world"

    def test_hash_consistency(self):
        a = SensitiveId("123456789012")
        b = SensitiveId("123456789012")
        assert hash(a) == hash(b)

    def test_hash_usable_as_dict_key(self):
        sid = SensitiveId("123456789012")
        d = {sid: "value"}
        assert d[sid] == "value"
        assert d[SensitiveId("123456789012")] == "value"

    def test_hash_usable_in_set(self):
        s = {SensitiveId("aaa"), SensitiveId("bbb"), SensitiveId("aaa")}
        assert len(s) == 2

    def test_bool_truthy(self):
        assert bool(SensitiveId("x"))

    def test_bool_falsy(self):
        assert not bool(SensitiveId(""))

    def test_len(self):
        assert len(SensitiveId("12345")) == 5

    def test_format_string_does_not_leak(self):
        sid = SensitiveId("123456789012")
        msg = f"Account: {sid}"
        assert "123456789012" not in msg
        assert "***9012" in msg

    def test_logging_style_interpolation_does_not_leak(self):
        sid = SensitiveId("123456789012")
        msg = "Account: %s" % sid
        assert "123456789012" not in msg


class TestIdentifierClass:
    """IdentifierClass enum and alias_prefix."""

    def test_all_classes_have_prefix(self):
        for cls in IdentifierClass:
            assert isinstance(cls.alias_prefix, str)
            assert len(cls.alias_prefix) > 0

    def test_account_prefix(self):
        assert IdentifierClass.ACCOUNT.alias_prefix == "acct"

    def test_resource_prefix(self):
        assert IdentifierClass.RESOURCE.alias_prefix == "res"

    def test_prefixes_are_unique(self):
        prefixes = [cls.alias_prefix for cls in IdentifierClass]
        assert len(prefixes) == len(set(prefixes)), "Alias prefixes must be unique"
