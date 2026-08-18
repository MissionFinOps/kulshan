"""Kulshan pseudonymization engine.

Single privacy layer for all output paths. Replaces the partial-masking
approach in redact.py with deterministic HMAC-derived aliases.
"""
from __future__ import annotations

from kulshan.pseudonym.classifier import ColumnClassification
from kulshan.pseudonym.engine import PseudonymizationEngine
from kulshan.pseudonym.policy import PolicyMode, PseudonymPolicy
from kulshan.pseudonym.types import IdentifierClass, SensitiveId

__all__ = [
    "ColumnClassification",
    "IdentifierClass",
    "PolicyMode",
    "PseudonymizationEngine",
    "PseudonymPolicy",
    "SensitiveId",
]
