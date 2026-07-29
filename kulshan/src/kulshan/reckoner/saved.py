"""Strict JSON saved-query definitions and deterministic resolution."""

from __future__ import annotations

import json
from pathlib import Path

from kulshan.reckoner.contracts import QuerySpec, ReckonerContractError


def load_saved_query(path: str | Path) -> QuerySpec:
    p = Path(path)
    if p.suffix.lower() != ".json":
        raise ReckonerContractError("saved queries must use .json")
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ReckonerContractError("saved query must be valid JSON") from exc
    if not isinstance(data, dict):
        raise ReckonerContractError("saved query root must be an object")
    return QuerySpec.from_dict(data)


def save_query(query: QuerySpec, path: str | Path) -> None:
    Path(path).write_text(
        json.dumps(query.to_dict(), indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def resolve_query(
    name: str,
    *,
    explicit: Path | None = None,
    project: Path | None = None,
    workspace: Path | None = None,
    built_in: Path | None = None,
) -> QuerySpec:
    for candidate in (explicit, project, workspace, built_in):
        if candidate is not None and candidate.exists():
            return load_saved_query(candidate)
    raise FileNotFoundError(f"saved query not found: {name}")
