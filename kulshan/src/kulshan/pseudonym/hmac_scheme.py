"""HMAC-SHA256 alias derivation scheme.

Produces deterministic, fixed-length pseudonym aliases from
a workspace secret and a canonical identifier form.

Properties:
- Deterministic: same (secret, canonical) always produces same alias.
- Fixed length: alias token is ALWAYS exactly 16 lowercase hex characters.
- Stateless: no lookup table, no counter, no cross-row state.
- One-way: cannot recover original from alias without the secret.
- Class-prefixed: each identifier class has a distinct human-readable prefix.
"""
from __future__ import annotations

import hashlib
import hmac

from kulshan.pseudonym.types import IdentifierClass

# Fixed displayed token length: 16 hex characters = 64 bits
_TOKEN_HEX_LENGTH = 16


def derive_alias(secret: bytes, canonical_form: str, identifier_class: IdentifierClass) -> str:
    """Derive a pseudonym alias from a canonical identifier.

    Args:
        secret: 32-byte workspace pseudonymization secret.
        canonical_form: Output of canonicalize() for the identifier.
        identifier_class: Classification determining the alias prefix.

    Returns:
        Alias string in format: {prefix}_{16 hex chars}
        Example: acct_7f31c2a9102d774b
    """
    digest = hmac.new(secret, canonical_form.encode("utf-8"), hashlib.sha256).hexdigest()
    token = digest[:_TOKEN_HEX_LENGTH]
    prefix = identifier_class.alias_prefix
    return f"{prefix}_{token}"


def derive_token(secret: bytes, canonical_form: str) -> str:
    """Derive just the hex token without prefix.

    Useful for composing ARN aliases where individual components
    are pseudonymized separately.

    Args:
        secret: 32-byte workspace pseudonymization secret.
        canonical_form: Canonical identifier string.

    Returns:
        16 lowercase hexadecimal characters.
    """
    digest = hmac.new(secret, canonical_form.encode("utf-8"), hashlib.sha256).hexdigest()
    return digest[:_TOKEN_HEX_LENGTH]
