"""Shared scoring utilities used across packs and the orchestrator."""
from __future__ import annotations


def grade(score: int) -> str:
    """Convert a 0-100 numeric score to a letter grade."""
    if score >= 97: return "A+"
    if score >= 93: return "A"
    if score >= 90: return "A-"
    if score >= 87: return "B+"
    if score >= 83: return "B"
    if score >= 80: return "B-"
    if score >= 77: return "C+"
    if score >= 73: return "C"
    if score >= 70: return "C-"
    if score >= 60: return "D"
    return "F"


def validate_weights(weights: dict) -> bool:
    """Assert that scoring weights sum to 1.0 (within floating point tolerance)."""
    total = sum(weights.values())
    return abs(total - 1.0) < 0.001
