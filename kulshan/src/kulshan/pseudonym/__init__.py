"""Kulshan pseudonymization engine.

Single privacy layer for all output paths. Replaces the partial-masking
approach in redact.py with deterministic HMAC-derived aliases.
"""
from __future__ import annotations

from kulshan.pseudonym.types import IdentifierClass, SensitiveId

__all__ = ["IdentifierClass", "SensitiveId"]
