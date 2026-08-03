"""Capability-aware terminal rendering for renderer-neutral query results."""

from __future__ import annotations

from io import StringIO

from rich import box
from rich.console import Console
from rich.table import Table
from rich.text import Text

from kulshan.reckoner.contracts import QueryResult


def _currency(result: QueryResult) -> str | None:
    """Return an available currency label without assuming one."""
    for metadata in (result.display_metadata, result.cost_basis):
        value = metadata.get("currency")
        if value:
            return str(value)
    return None


def _number(value: object, *, currency: str | None = None) -> str:
    number = float(value or 0)
    if currency:
        return f"{currency} {number:,.2f}"
    if number.is_integer():
        return f"{number:,.0f}"
    return f"{number:,.4f}".rstrip("0").rstrip(".")


def render_result(result: QueryResult, *, mode: str = "standard", ascii_only: bool = False) -> str:
    """Render a query result as a captured Rich terminal string."""
    if mode not in {"compact", "standard", "wide"}:
        raise ValueError("unsupported terminal mode")

    output = StringIO()
    console = Console(file=output, force_terminal=not ascii_only)
    currency = _currency(result)
    total = _number(result.totals.get("value", 0), currency=currency)

    if mode == "compact":
        console.print(
            Text.assemble((result.query.metric, "bold"), "  ", (f"Total: {total}", "cyan"))
        )
        return output.getvalue()

    arrow = "->" if ascii_only else "→"
    console.print(
        Text.assemble(
            (result.query.metric, "bold"),
            f"  {result.period.start} {arrow} {result.period.end}",
            f"  [{result.execution_source.value}]",
        )
    )
    console.print(Text.assemble(("Total: ", "bold"), (total, "bold cyan")))

    if result.rows:
        table = Table(box=box.ASCII if ascii_only else box.ROUNDED, show_header=True)
        for column in result.columns:
            numeric = column.data_type == "number"
            table.add_column(
                column.label,
                justify="right" if numeric else "left",
                no_wrap=mode == "wide",
            )
        for row in result.rows:
            values = []
            for column in result.columns:
                value = row.get(column.column_id, "")
                values.append(
                    _number(value, currency=currency if column.unit == "currency" else None)
                    if column.data_type == "number" and value is not None
                    else str(value if value is not None else "")
                )
            table.add_row(*values)
        console.print(table)
    else:
        console.print("No results for this period", style="yellow")

    footer = [result.formula_id or "formula unavailable", f"{len(result.rows)} rows"]
    if result.execution_duration_ms is not None:
        footer.append(f"{result.execution_duration_ms} ms")
    console.print(" · ".join(footer), style="dim")
    return output.getvalue()
