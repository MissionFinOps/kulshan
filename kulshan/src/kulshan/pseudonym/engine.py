"""Pseudonymization engine: the single privacy transformation layer.

Transforms JSON-like payloads by classifying fields and values,
canonicalizing identifiers, and replacing them with deterministic
HMAC-derived aliases.

This engine:
- Never mutates its input (returns a new structure).
- Never logs or exposes the workspace secret.
- Fails closed if the secret is unavailable.
- Supports structured field classification and free-text pattern scanning.
"""
from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

from kulshan.pseudonym.canonical import canonicalize, classify_and_canonicalize
from kulshan.pseudonym.classifier import (
    classify_field,
    is_passthrough_field,
    is_text_field,
    scan_text_for_identifiers,
)
from kulshan.pseudonym.hmac_scheme import derive_alias
from kulshan.pseudonym.policy import PseudonymPolicy
from kulshan.pseudonym.secret import SecretCorruptError, load_or_create_secret
from kulshan.pseudonym.types import IdentifierClass


class PseudonymizationEngine:
    """Single pseudonymization engine for all Kulshan output paths.

    Thread-safety: instances are safe for concurrent reads (the secret
    and policy are immutable after construction). No mutable state.
    """

    def __init__(self, secret: bytes, policy: PseudonymPolicy):
        if len(secret) != 32:
            raise ValueError("Workspace secret must be exactly 32 bytes")
        self._secret = secret
        self._policy = policy

    @classmethod
    def create(
        cls,
        workspace_path: Path,
        policy: PseudonymPolicy,
    ) -> "PseudonymizationEngine":
        """Create an engine by loading the workspace secret.

        Raises:
            SecretCorruptError: If the secret file is corrupt (fail-closed).
        """
        secret = load_or_create_secret(workspace_path)
        return cls(secret, policy)

    @property
    def policy(self) -> PseudonymPolicy:
        return self._policy

    @property
    def is_active(self) -> bool:
        """Whether pseudonymization should be applied given current policy."""
        return self._policy.should_pseudonymize

    def pseudonymize_value(self, value: str, identifier_class: IdentifierClass) -> str:
        """Pseudonymize a single known-class identifier value.

        Args:
            value: Raw identifier string.
            identifier_class: Known classification of this value.

        Returns:
            HMAC-derived alias string.
        """
        if not value:
            return value
        canonical = canonicalize(value, identifier_class)
        return derive_alias(self._secret, canonical, identifier_class)

    def pseudonymize_text(self, text: str) -> str:
        """Scan free text for embedded identifiers and replace them.

        Preserves non-identifier portions of the text intact.
        Replaces each detected identifier with its class-appropriate alias.
        """
        if not text:
            return text

        matches = scan_text_for_identifiers(text)
        if not matches:
            return text

        # Build output by replacing matches from right to left
        # (so positions remain valid)
        result = text
        for matched_value, id_class, start, end in reversed(matches):
            alias = self.pseudonymize_value(matched_value, id_class)
            result = result[:start] + alias + result[end:]

        return result

    def pseudonymize_payload(self, payload: Any) -> Any:
        """Deep-walk a JSON-like structure and pseudonymize identifier fields.

        Returns a NEW structure. The input is never mutated.

        Supported types: dict, list, tuple, str, int, float, bool, None.
        Unsupported objects raise TypeError (fail-closed).
        """
        if not self.is_active:
            return payload
        return self._walk(payload, field_key="")

    def _walk(self, obj: Any, field_key: str) -> Any:
        if obj is None:
            return None
        if isinstance(obj, bool):
            return obj
        if isinstance(obj, (int, float)):
            return obj
        if isinstance(obj, str):
            return self._transform_string(obj, field_key)
        if isinstance(obj, dict):
            return {k: self._walk(v, k) for k, v in obj.items()}
        if isinstance(obj, (list, tuple)):
            result = [self._walk(item, field_key) for item in obj]
            return type(obj)(result) if isinstance(obj, tuple) else result
        # Unsupported type: fail closed
        raise TypeError(
            f"PseudonymizationEngine cannot safely handle type {type(obj).__name__}. "
            f"Convert to a JSON-safe type before pseudonymization."
        )

    def _transform_string(self, value: str, field_key: str) -> str:
        """Transform a string value based on field context and content."""
        if not value:
            return value

        # Check if field is explicitly passthrough
        if field_key and is_passthrough_field(field_key):
            return value

        # Check if field has a known identifier class
        if field_key:
            id_class = classify_field(field_key)
            if id_class is not None:
                return self.pseudonymize_value(value, id_class)

        # Text fields and unknown fields: scan for embedded identifiers
        if field_key and (is_text_field(field_key) or not is_passthrough_field(field_key)):
            return self.pseudonymize_text(value)

        return self.pseudonymize_text(value)

    def __repr__(self) -> str:
        """Safe repr that never exposes the secret."""
        return f"PseudonymizationEngine(policy={self._policy!r})"

    def __str__(self) -> str:
        """Safe str that never exposes the secret."""
        return f"PseudonymizationEngine(active={self.is_active})"
