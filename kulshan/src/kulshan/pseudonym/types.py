"""Core types for the pseudonymization engine."""
from __future__ import annotations

from enum import Enum
from typing import Any


class IdentifierClass(Enum):
    """Classification of customer-identifying values."""

    ACCOUNT = "account"
    RESOURCE = "resource"
    ARN = "arn"
    SAVINGS_PLAN = "sp"
    RESERVED_INSTANCE = "ri"
    INVOICE = "invoice"
    S3_BUCKET = "bucket"
    HOSTNAME = "hostname"
    EMAIL = "email"
    IP_ADDRESS = "ip"
    TAG_VALUE = "tag"
    UNKNOWN = "unknown"

    @property
    def alias_prefix(self) -> str:
        """Return the human-readable prefix for aliases of this class."""
        return _PREFIX_MAP[self]


_PREFIX_MAP = {
    IdentifierClass.ACCOUNT: "acct",
    IdentifierClass.RESOURCE: "res",
    IdentifierClass.ARN: "arn",
    IdentifierClass.SAVINGS_PLAN: "sp",
    IdentifierClass.RESERVED_INSTANCE: "ri",
    IdentifierClass.INVOICE: "inv",
    IdentifierClass.S3_BUCKET: "bucket",
    IdentifierClass.HOSTNAME: "host",
    IdentifierClass.EMAIL: "user",
    IdentifierClass.IP_ADDRESS: "ip",
    IdentifierClass.TAG_VALUE: "tag",
    IdentifierClass.UNKNOWN: "id",
}


class SensitiveId:
    """Wrapper for customer-identifying strings that prevents accidental leakage.

    __str__ and __repr__ return a masked form, never the raw value.
    Use .raw to access the original for internal computation.

    Supports equality and hashing on the raw value so that SensitiveId
    instances work correctly as dict keys, set members, and lookup values.
    """

    __slots__ = ("_raw",)

    def __init__(self, raw: str):
        self._raw = raw

    @property
    def raw(self) -> str:
        """Access the real identifier value for internal logic."""
        return self._raw

    def __str__(self) -> str:
        """Safe string representation. Never exposes the full raw value."""
        if not self._raw:
            return "***"
        if len(self._raw) >= 4:
            return f"***{self._raw[-4:]}"
        return "***"

    def __repr__(self) -> str:
        return f"SensitiveId({self.__str__()!r})"

    def __eq__(self, other: Any) -> bool:
        if isinstance(other, SensitiveId):
            return self._raw == other._raw
        if isinstance(other, str):
            return self._raw == other
        return NotImplemented

    def __ne__(self, other: Any) -> bool:
        result = self.__eq__(other)
        if result is NotImplemented:
            return result
        return not result

    def __hash__(self) -> int:
        return hash(self._raw)

    def __bool__(self) -> bool:
        return bool(self._raw)

    def __len__(self) -> int:
        return len(self._raw)
