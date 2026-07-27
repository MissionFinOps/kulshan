"""Safe schema loading for declarative Reckoner modules.

Module files use the JSON-compatible subset of YAML. The standard-library JSON
parser is intentionally used so PR 0 does not add a YAML dependency or support
tags, constructors, aliases, or executable expressions.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from kulshan.reckoner.contracts import QuerySpec, ReckonerContractError

MODULE_SCHEMA_VERSION = "1.0"
_MODULE_ID_RE = re.compile(r"^[a-z][a-z0-9-]{1,63}$")
_ALLOWED_OVERRIDES = frozenset(
    {
        "metric",
        "period",
        "groupings",
        "filters",
        "exclusions",
        "comparison",
        "sort",
        "limit",
        "visualization",
        "execution_source",
        "output_format",
    }
)
_FORBIDDEN_KEYS = frozenset(
    {"sql", "python", "shell", "command", "credentials", "customer_data", "expression", "exec"}
)


@dataclass(frozen=True)
class ModuleDefinition:
    schema_version: str
    module_id: str
    question: str
    description: str
    query_defaults: QuerySpec
    allowed_overrides: tuple[str, ...]
    output_sections: tuple[str, ...]
    suggested_drilldowns: tuple[str, ...]
    chart_preference: str
    explanation_text: str
    freshness_requirements: tuple[str, ...]
    limitations: tuple[str, ...]
    formula_provenance_references: tuple[str, ...]

    def __post_init__(self) -> None:
        if self.schema_version != MODULE_SCHEMA_VERSION:
            raise ReckonerContractError(
                f"Unsupported module schema_version {self.schema_version!r}"
            )
        if not _MODULE_ID_RE.fullmatch(self.module_id):
            raise ReckonerContractError(f"Invalid module_id: {self.module_id!r}")
        if not self.question or not self.description:
            raise ReckonerContractError("module question and description are required")
        unknown = sorted(set(self.allowed_overrides) - _ALLOWED_OVERRIDES)
        if unknown:
            raise ReckonerContractError(f"Unknown allowed overrides: {', '.join(unknown)}")
        for drilldown in self.suggested_drilldowns:
            if drilldown not in self.query_defaults.groupings:
                # A suggestion may expand beyond defaults, but it must remain a dimension ID.
                from kulshan.reckoner.contracts import validate_dimension_id

                validate_dimension_id(drilldown)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "module_id": self.module_id,
            "question": self.question,
            "description": self.description,
            "query_defaults": self.query_defaults.to_dict(),
            "allowed_overrides": list(self.allowed_overrides),
            "output_sections": list(self.output_sections),
            "suggested_drilldowns": list(self.suggested_drilldowns),
            "chart_preference": self.chart_preference,
            "explanation_text": self.explanation_text,
            "freshness_requirements": list(self.freshness_requirements),
            "limitations": list(self.limitations),
            "formula_provenance_references": list(self.formula_provenance_references),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> ModuleDefinition:
        allowed = {
            "schema_version",
            "module_id",
            "question",
            "description",
            "query_defaults",
            "allowed_overrides",
            "output_sections",
            "suggested_drilldowns",
            "chart_preference",
            "explanation_text",
            "freshness_requirements",
            "limitations",
            "formula_provenance_references",
        }
        unknown = sorted(set(data) - allowed)
        if unknown:
            raise ReckonerContractError(f"module contains unknown fields: {', '.join(unknown)}")
        _reject_forbidden_fields(data)
        query_defaults = data.get("query_defaults")
        if not isinstance(query_defaults, Mapping):
            raise ReckonerContractError("module query_defaults must be an object")
        sequence_fields = (
            "allowed_overrides",
            "output_sections",
            "suggested_drilldowns",
            "freshness_requirements",
            "limitations",
            "formula_provenance_references",
        )
        for name in sequence_fields:
            if not isinstance(data.get(name, []), list):
                raise ReckonerContractError(f"module {name} must be a list")
        return cls(
            schema_version=str(data.get("schema_version", "")),
            module_id=str(data.get("module_id", "")),
            question=str(data.get("question", "")),
            description=str(data.get("description", "")),
            query_defaults=QuerySpec.from_dict(query_defaults),
            allowed_overrides=tuple(str(v) for v in data.get("allowed_overrides", [])),
            output_sections=tuple(str(v) for v in data.get("output_sections", [])),
            suggested_drilldowns=tuple(str(v) for v in data.get("suggested_drilldowns", [])),
            chart_preference=str(data.get("chart_preference", "table")),
            explanation_text=str(data.get("explanation_text", "")),
            freshness_requirements=tuple(str(v) for v in data.get("freshness_requirements", [])),
            limitations=tuple(str(v) for v in data.get("limitations", [])),
            formula_provenance_references=tuple(
                str(v) for v in data.get("formula_provenance_references", [])
            ),
        )


def _reject_forbidden_fields(value: Any, path: str = "module") -> None:
    if isinstance(value, Mapping):
        for key, child in value.items():
            normalized = str(key).lower().replace("-", "_")
            if normalized in _FORBIDDEN_KEYS:
                raise ReckonerContractError(f"{path}.{key} is executable or forbidden")
            _reject_forbidden_fields(child, f"{path}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _reject_forbidden_fields(child, f"{path}[{index}]")


def load_module(path: str | Path) -> ModuleDefinition:
    """Load a module using the safe JSON-compatible YAML subset."""
    module_path = Path(path)
    try:
        data = json.loads(module_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ReckonerContractError(
            "module must use JSON-compatible YAML; tags and executable YAML are unsupported"
        ) from exc
    if not isinstance(data, Mapping):
        raise ReckonerContractError("module root must be an object")
    return ModuleDefinition.from_dict(data)
