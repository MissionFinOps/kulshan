"""Capability-aware terminal rendering for renderer-neutral query results."""

from __future__ import annotations

from kulshan.reckoner.contracts import QueryResult


def render_result(result: QueryResult, *, mode: str = "standard", ascii_only: bool = False) -> str:
    if mode not in {"compact", "standard", "wide"}:
        raise ValueError("unsupported terminal mode")
    arrow = "->" if ascii_only else "→"
    lines = [f"{result.query.metric}  {result.period.start} {arrow} {result.period.end}"]
    names = [column.name for column in result.columns]
    if mode != "compact" and names:
        lines.append(" | ".join(names))
        lines.extend(" | ".join(str(row.get(name, "")) for name in names) for row in result.rows)
    lines.append(f"Total: {result.totals.get('value', 0)}")
    return "\n".join(lines)
