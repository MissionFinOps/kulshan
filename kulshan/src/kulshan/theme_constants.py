"""Shared theme constants for terminal and HTML renderers."""
from __future__ import annotations

from typing import Dict

TOOL_ICONS: Dict[str, str] = {
    "cost": "\U0001f4b0",       # 💰 money bag
    "security": "\U0001f6e1\ufe0f",  # 🛡️ shield
    "sweep": "\U0001f9f9",      # 🧹 broom
    "dr": "\U0001f691",         # 🚑 ambulance
    "age": "\u23f3",            # ⏳ hourglass
    "drift": "\U0001f9ed",      # 🧭 compass
    "tag": "\U0001f3f7\ufe0f",  # 🏷️ label
    "pulse": "\U0001f493",      # 💓 heartbeat
    "limit": "\U0001f4ca",      # 📊 bar chart
    "topo": "\U0001f310",       # 🌐 globe
}

# Grade → color (hex for HTML, Rich names for terminal)
GRADE_COLORS_HEX: Dict[str, str] = {
    "A": "#2e7d32",
    "B": "#1565c0",
    "C": "#f57f17",
    "D": "#e65100",
    "F": "#c62828",
}

# Severity → color (hex for HTML)
SEVERITY_COLORS_HEX: Dict[str, str] = {
    "critical": "#c62828",
    "high": "#e65100",
    "medium": "#f57f17",
    "low": "#9e9e9e",
    "info": "#757575",
}

# Severity → Rich style for terminal
SEVERITY_STYLES: Dict[str, str] = {
    "critical": "red bold",
    "high": "dark_orange",
    "medium": "yellow",
    "low": "dim",
    "info": "dim",
}
