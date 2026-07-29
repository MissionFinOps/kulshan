"""Shared deterministic QueryResult renderers."""

from __future__ import annotations

import csv
import io
import json

from kulshan.reckoner.contracts import QueryResult


def render_json(result: QueryResult) -> str:
    return json.dumps(result.to_dict(), indent=2, sort_keys=True) + "\n"


def render_csv(result: QueryResult) -> str:
    out = io.StringIO()
    names = [c.column_id for c in result.columns]
    writer = csv.DictWriter(out, fieldnames=names, lineterminator="\n")
    writer.writeheader()
    writer.writerows(result.rows)
    return out.getvalue()


def render_markdown(result: QueryResult) -> str:
    names = [c.column_id for c in result.columns]
    lines = ["| " + " | ".join(names) + " |", "| " + " | ".join("---" for _ in names) + " |"]
    lines.extend(
        "| " + " | ".join(str(row.get(name, "")) for name in names) + " |" for row in result.rows
    )
    return "\n".join(lines) + "\n"


def provenance_sidecar(result: QueryResult) -> dict[str, object]:
    return {
        "query": result.query.to_dict(),
        "period": result.period.to_dict(),
        "formula_id": result.formula_id,
        "formula_version": result.formula_version,
        "execution_source": result.execution_source.value,
        "rows_returned": result.rows_returned,
        "source_manifests": [item.to_dict() for item in result.source_manifests],
    }
