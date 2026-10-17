"""Protect spreadsheet cells without altering numeric evidence."""
from __future__ import annotations

import re
from typing import Any

_NUMBER = re.compile(r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?\Z")


def safe_csv_value(value: Any) -> Any:
    """Quote formula-like text, including leading whitespace bypasses."""
    if not isinstance(value, str):
        return value
    stripped = value.lstrip()
    if stripped.startswith(("=", "+", "-", "@")) and not _NUMBER.fullmatch(stripped):
        return "'" + value
    return value
