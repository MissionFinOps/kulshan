"""Versioned, renderer-neutral Reckoner contracts.

These types describe requests, results, planning decisions, provenance, and
trust inspection. They intentionally contain no execution implementation.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

QUERY_SPEC_VERSION = "1.0"
QUERY_RESULT_VERSION = "1.0"
PROVENANCE_VERSION = "1.0"
MAX_RESULT_LIMIT = 10_000
SUPPORTED_PERIOD_IDS = frozenset(
    {
        "current-billing-period",
        "previous-complete-month",
        "last-7-days",
        "last-30-days",
        "last-3-complete-months",
        "last-6-complete-months",
        "last-12-complete-months",
        "last-13-billing-periods",
        "last-18-billing-periods",
        "year-to-date",
        "previous-year-to-date",
        "custom",
    }
)


class ReckonerContractError(ValueError):
    """Raised when a serialized Reckoner contract is invalid."""


class StableEnum(str, Enum):
    """String enum with stable serialized values."""


class FilterOperator(StableEnum):
    EQUALS = "equals"
    NOT_EQUALS = "not-equals"
    IN = "in"
    NOT_IN = "not-in"
    CONTAINS = "contains"
    STARTS_WITH = "starts-with"
    IS_NULL = "is-null"
    IS_NOT_NULL = "is-not-null"
    GREATER_THAN = "greater-than"
    LESS_THAN = "less-than"
    BETWEEN = "between"


class ExecutionSource(StableEnum):
    AUTO = "auto"
    CACHE = "cache"
    LOCAL = "local"
    S3 = "s3"


class OutputFormat(StableEnum):
    JSON = "json"
    CSV = "csv"
    TERMINAL = "terminal"


class Visualization(StableEnum):
    TABLE = "table"
    BAR = "bar"
    LINE = "line"
    KPI = "kpi"
    NONE = "none"


class SortDirection(StableEnum):
    ASCENDING = "asc"
    DESCENDING = "desc"


class ComparisonKind(StableEnum):
    NONE = "none"
    PREVIOUS_PERIOD = "previous-period"
    PREVIOUS_YEAR = "previous-year"
    CUSTOM = "custom"


class PlannerReason(StableEnum):
    EXPLICIT_REQUEST = "explicit-request"
    CACHE_COVERAGE = "cache-coverage"
    LOCAL_AVAILABLE = "local-available"
    S3_REQUIRED = "s3-required"
    UNSATISFIED = "unsatisfied"


_DIMENSION_RE = re.compile(r"^[a-z][a-z0-9-]*$")
_DYNAMIC_KEY_RE = re.compile(r"^[A-Za-z0-9_.:/+=@-]{1,128}$")
_BOUNDARY_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}(?:T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})?)?$"
)


def _strict_mapping(data: Mapping[str, Any], allowed: set[str], name: str) -> None:
    unknown = sorted(set(data) - allowed)
    if unknown:
        raise ReckonerContractError(f"{name} contains unknown fields: {', '.join(unknown)}")


def _enum(enum_type: type[StableEnum], value: Any, field_name: str) -> StableEnum:
    try:
        return enum_type(value)
    except (TypeError, ValueError) as exc:
        allowed = ", ".join(item.value for item in enum_type)
        raise ReckonerContractError(f"{field_name} must be one of: {allowed}") from exc


def validate_dimension_id(value: str) -> str:
    """Validate static and dynamic dimension identifiers."""
    if value.startswith(("tag:", "cost-category:")):
        prefix, key = value.split(":", 1)
        if not _DYNAMIC_KEY_RE.fullmatch(key):
            raise ReckonerContractError(f"Invalid {prefix} key: {key!r}")
        return value
    if not _DIMENSION_RE.fullmatch(value):
        raise ReckonerContractError(f"Invalid dimension ID: {value!r}")
    return value


@dataclass(frozen=True)
class PeriodSpec:
    """Named period or explicit half-open custom range."""

    period_id: str
    start: str | None = None
    end: str | None = None
    range_rule: str = "start <= usage_time < end"

    def __post_init__(self) -> None:
        if not self.period_id:
            raise ReckonerContractError("period.period_id is required")
        if self.period_id not in SUPPORTED_PERIOD_IDS:
            raise ReckonerContractError(f"unsupported period: {self.period_id}")
        custom = self.period_id == "custom"
        if custom != (self.start is not None and self.end is not None):
            raise ReckonerContractError(
                "custom periods require start and end; named periods forbid them"
            )
        for name, value in (("start", self.start), ("end", self.end)):
            if value is not None and not _BOUNDARY_RE.fullmatch(value):
                raise ReckonerContractError(f"period.{name} is not an ISO date or timestamp")
        if self.start is not None and self.end is not None and self.start >= self.end:
            raise ReckonerContractError("period.start must be before period.end")
        if self.range_rule != "start <= usage_time < end":
            raise ReckonerContractError("period range_rule must express the half-open range")

    def to_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {"period_id": self.period_id, "range_rule": self.range_rule}
        if self.start is not None:
            data.update(start=self.start, end=self.end)
        return data

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> PeriodSpec:
        _strict_mapping(data, {"period_id", "start", "end", "range_rule"}, "period")
        return cls(
            period_id=str(data.get("period_id", "")),
            start=data.get("start"),
            end=data.get("end"),
            range_rule=str(data.get("range_rule", "start <= usage_time < end")),
        )


@dataclass(frozen=True)
class ComparisonSpec:
    kind: ComparisonKind = ComparisonKind.NONE
    period: PeriodSpec | None = None

    def __post_init__(self) -> None:
        if self.kind is ComparisonKind.CUSTOM and self.period is None:
            raise ReckonerContractError("custom comparison requires a period")
        if self.kind is not ComparisonKind.CUSTOM and self.period is not None:
            raise ReckonerContractError("only custom comparison accepts a period")

    def to_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {"kind": self.kind.value}
        if self.period is not None:
            data["period"] = self.period.to_dict()
        return data

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> ComparisonSpec:
        _strict_mapping(data, {"kind", "period"}, "comparison")
        kind = _enum(ComparisonKind, data.get("kind", "none"), "comparison.kind")
        period_data = data.get("period")
        return cls(
            kind=kind,  # type: ignore[arg-type]
            period=PeriodSpec.from_dict(period_data) if isinstance(period_data, Mapping) else None,
        )


@dataclass(frozen=True)
class FilterSpec:
    dimension: str
    operator: FilterOperator
    values: tuple[Any, ...] = ()

    def __post_init__(self) -> None:
        validate_dimension_id(self.dimension)
        null_operator = self.operator in {FilterOperator.IS_NULL, FilterOperator.IS_NOT_NULL}
        if null_operator and self.values:
            raise ReckonerContractError(f"{self.operator.value} does not accept values")
        if not null_operator and not self.values:
            raise ReckonerContractError(f"{self.operator.value} requires at least one value")
        if self.operator in {FilterOperator.IN, FilterOperator.NOT_IN} and not self.values:
            raise ReckonerContractError(f"{self.operator.value} value list cannot be empty")
        if self.operator is FilterOperator.BETWEEN and len(self.values) != 2:
            raise ReckonerContractError("between requires exactly two values")
        if (
            self.operator
            not in {
                FilterOperator.IN,
                FilterOperator.NOT_IN,
                FilterOperator.BETWEEN,
                FilterOperator.IS_NULL,
                FilterOperator.IS_NOT_NULL,
            }
            and len(self.values) != 1
        ):
            raise ReckonerContractError(f"{self.operator.value} requires exactly one value")

    def to_dict(self) -> dict[str, Any]:
        return {
            "dimension": self.dimension,
            "operator": self.operator.value,
            "values": list(self.values),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> FilterSpec:
        _strict_mapping(data, {"dimension", "operator", "values"}, "filter")
        values = data.get("values", [])
        if not isinstance(values, list):
            raise ReckonerContractError("filter.values must be a list")
        return cls(
            dimension=str(data.get("dimension", "")),
            operator=_enum(FilterOperator, data.get("operator"), "filter.operator"),  # type: ignore[arg-type]
            values=tuple(values),
        )


@dataclass(frozen=True)
class SortSpec:
    field: str
    direction: SortDirection = SortDirection.DESCENDING

    def __post_init__(self) -> None:
        if not self.field:
            raise ReckonerContractError("sort.field is required")

    def to_dict(self) -> dict[str, str]:
        return {"field": self.field, "direction": self.direction.value}

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> SortSpec:
        _strict_mapping(data, {"field", "direction"}, "sort")
        return cls(
            field=str(data.get("field", "")),
            direction=_enum(SortDirection, data.get("direction", "desc"), "sort.direction"),  # type: ignore[arg-type]
        )


@dataclass(frozen=True)
class QuerySpec:
    """Versioned query request with no executable content."""

    metric: str
    period: PeriodSpec
    schema_version: str = QUERY_SPEC_VERSION
    groupings: tuple[str, ...] = ()
    filters: tuple[FilterSpec, ...] = ()
    exclusions: tuple[FilterSpec, ...] = ()
    comparison: ComparisonSpec = field(default_factory=ComparisonSpec)
    sort: tuple[SortSpec, ...] = ()
    limit: int = 100
    visualization: Visualization = Visualization.TABLE
    execution_source: ExecutionSource = ExecutionSource.AUTO
    output_format: OutputFormat = OutputFormat.JSON

    def __post_init__(self) -> None:
        if self.schema_version != QUERY_SPEC_VERSION:
            raise ReckonerContractError(
                f"Unsupported QuerySpec schema_version {self.schema_version!r}"
            )
        if not self.metric:
            raise ReckonerContractError("metric is required")
        if len(self.groupings) > 3:
            raise ReckonerContractError("QuerySpec supports at most three grouping dimensions")
        for grouping in self.groupings:
            validate_dimension_id(grouping)
        if len(set(self.groupings)) != len(self.groupings):
            raise ReckonerContractError("duplicate grouping dimensions are not allowed")
        if not isinstance(self.limit, int) or isinstance(self.limit, bool):
            raise ReckonerContractError("limit must be an integer")
        if not 1 <= self.limit <= MAX_RESULT_LIMIT:
            raise ReckonerContractError(f"limit must be between 1 and {MAX_RESULT_LIMIT}")

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "metric": self.metric,
            "period": self.period.to_dict(),
            "groupings": list(self.groupings),
            "filters": [item.to_dict() for item in self.filters],
            "exclusions": [item.to_dict() for item in self.exclusions],
            "comparison": self.comparison.to_dict(),
            "sort": [item.to_dict() for item in self.sort],
            "limit": self.limit,
            "visualization": self.visualization.value,
            "execution_source": self.execution_source.value,
            "output_format": self.output_format.value,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> QuerySpec:
        allowed = {
            "schema_version",
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
        _strict_mapping(data, allowed, "QuerySpec")
        period = data.get("period")
        if not isinstance(period, Mapping):
            raise ReckonerContractError("period must be an object")
        groupings = data.get("groupings", [])
        filters = data.get("filters", [])
        exclusions = data.get("exclusions", [])
        sort = data.get("sort", [])
        if not all(isinstance(value, list) for value in (groupings, filters, exclusions, sort)):
            raise ReckonerContractError("groupings, filters, exclusions, and sort must be lists")
        comparison = data.get("comparison", {"kind": "none"})
        if not isinstance(comparison, Mapping):
            raise ReckonerContractError("comparison must be an object")
        return cls(
            schema_version=str(data.get("schema_version", "")),
            metric=str(data.get("metric", "")),
            period=PeriodSpec.from_dict(period),
            groupings=tuple(str(item) for item in groupings),
            filters=tuple(FilterSpec.from_dict(item) for item in filters),
            exclusions=tuple(FilterSpec.from_dict(item) for item in exclusions),
            comparison=ComparisonSpec.from_dict(comparison),
            sort=tuple(SortSpec.from_dict(item) for item in sort),
            limit=data.get("limit", 100),
            visualization=_enum(Visualization, data.get("visualization", "table"), "visualization"),  # type: ignore[arg-type]
            execution_source=_enum(
                ExecutionSource, data.get("execution_source", "auto"), "execution_source"
            ),  # type: ignore[arg-type]
            output_format=_enum(OutputFormat, data.get("output_format", "json"), "output_format"),  # type: ignore[arg-type]
        )


@dataclass(frozen=True)
class ResolvedRange:
    start: str
    end: str
    range_rule: str = "start <= usage_time < end"

    def __post_init__(self) -> None:
        if not _BOUNDARY_RE.fullmatch(self.start) or not _BOUNDARY_RE.fullmatch(self.end):
            raise ReckonerContractError("resolved range boundaries must be ISO dates or timestamps")
        if self.start >= self.end:
            raise ReckonerContractError("resolved range start must be before end")

    def to_dict(self) -> dict[str, str]:
        return {"start": self.start, "end": self.end, "range_rule": self.range_rule}

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> ResolvedRange:
        _strict_mapping(data, {"start", "end", "range_rule"}, "resolved range")
        return cls(
            start=str(data.get("start", "")),
            end=str(data.get("end", "")),
            range_rule=str(data.get("range_rule", "start <= usage_time < end")),
        )


@dataclass(frozen=True)
class ColumnDefinition:
    column_id: str
    label: str
    data_type: str
    unit: str | None = None
    sensitivity: str = "non-sensitive"
    machine_stable: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "column_id": self.column_id,
            "label": self.label,
            "data_type": self.data_type,
            "unit": self.unit,
            "sensitivity": self.sensitivity,
            "machine_stable": self.machine_stable,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> ColumnDefinition:
        _strict_mapping(
            data,
            {"column_id", "label", "data_type", "unit", "sensitivity", "machine_stable"},
            "column",
        )
        return cls(
            column_id=str(data.get("column_id", "")),
            label=str(data.get("label", "")),
            data_type=str(data.get("data_type", "")),
            unit=data.get("unit"),
            sensitivity=str(data.get("sensitivity", "non-sensitive")),
            machine_stable=bool(data.get("machine_stable", True)),
        )


@dataclass(frozen=True)
class SourceManifestRef:
    source_id: str
    manifest_uri: str | None = None
    schema_fingerprint: str | None = None
    redacted: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_id": self.source_id,
            "manifest_uri": self.manifest_uri,
            "schema_fingerprint": self.schema_fingerprint,
            "redacted": self.redacted,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> SourceManifestRef:
        _strict_mapping(
            data, {"source_id", "manifest_uri", "schema_fingerprint", "redacted"}, "source"
        )
        return cls(
            source_id=str(data.get("source_id", "")),
            manifest_uri=data.get("manifest_uri"),
            schema_fingerprint=data.get("schema_fingerprint"),
            redacted=bool(data.get("redacted", False)),
        )


@dataclass(frozen=True)
class PlannerDecision:
    selected_source: ExecutionSource | None
    reason: PlannerReason
    cache_coverage: str | None = None
    local_data_available: bool | None = None
    s3_estimate_required: bool = False
    confirmation_required: bool = False
    unsatisfied_requirement: str | None = None

    def __post_init__(self) -> None:
        if self.reason is PlannerReason.UNSATISFIED and not self.unsatisfied_requirement:
            raise ReckonerContractError("unsatisfied planner decision requires an explanation")
        if self.reason is not PlannerReason.UNSATISFIED and self.selected_source is None:
            raise ReckonerContractError("satisfied planner decision requires selected_source")

    def to_dict(self) -> dict[str, Any]:
        return {
            "selected_source": self.selected_source.value if self.selected_source else None,
            "reason": self.reason.value,
            "cache_coverage": self.cache_coverage,
            "local_data_available": self.local_data_available,
            "s3_estimate_required": self.s3_estimate_required,
            "confirmation_required": self.confirmation_required,
            "unsatisfied_requirement": self.unsatisfied_requirement,
        }


@dataclass(frozen=True)
class ProvenanceRecord:
    """Provenance for a future copied or adapted implementation."""

    record_id: str
    upstream_repository: str
    upstream_commit: str
    licence: str
    source_file: str
    source_locator: str
    upstream_blob_hash: str
    adaptation_type: str
    verification_status: str
    kulshan_destination: str | None = None
    material_changes: tuple[str, ...] = ()
    kulshan_formula_id: str | None = None
    kulshan_formula_version: str | None = None
    golden_fixture: str | None = None
    required_notice: str | None = None
    schema_version: str = PROVENANCE_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != PROVENANCE_VERSION:
            raise ReckonerContractError("unsupported provenance schema version")
        required = (
            self.record_id,
            self.upstream_repository,
            self.upstream_commit,
            self.licence,
            self.source_file,
            self.source_locator,
            self.upstream_blob_hash,
            self.adaptation_type,
            self.verification_status,
        )
        if not all(required):
            raise ReckonerContractError("provenance record is missing a required field")
        adopted = self.adaptation_type not in {"research-only", "not-adapted"}
        if adopted and not all(
            (self.kulshan_destination, self.kulshan_formula_id, self.kulshan_formula_version)
        ):
            raise ReckonerContractError(
                "adapted provenance requires destination and formula identity"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "record_id": self.record_id,
            "upstream_repository": self.upstream_repository,
            "upstream_commit": self.upstream_commit,
            "licence": self.licence,
            "source_file": self.source_file,
            "source_locator": self.source_locator,
            "upstream_blob_hash": self.upstream_blob_hash,
            "kulshan_destination": self.kulshan_destination,
            "adaptation_type": self.adaptation_type,
            "material_changes": list(self.material_changes),
            "kulshan_formula_id": self.kulshan_formula_id,
            "kulshan_formula_version": self.kulshan_formula_version,
            "golden_fixture": self.golden_fixture,
            "required_notice": self.required_notice,
            "verification_status": self.verification_status,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> ProvenanceRecord:
        allowed = {
            "schema_version",
            "record_id",
            "upstream_repository",
            "upstream_commit",
            "licence",
            "source_file",
            "source_locator",
            "upstream_blob_hash",
            "kulshan_destination",
            "adaptation_type",
            "material_changes",
            "kulshan_formula_id",
            "kulshan_formula_version",
            "golden_fixture",
            "required_notice",
            "verification_status",
        }
        _strict_mapping(data, allowed, "provenance record")
        return cls(
            **{key: data.get(key) for key in allowed if key not in {"material_changes"}},
            material_changes=tuple(data.get("material_changes", [])),
        )


@dataclass(frozen=True)
class TrustInspection:
    """Structured data for future --explain/--show-sql/--show-sources views."""

    metric: str
    cost_basis: Mapping[str, Any]
    formula_id: str | None
    formula_version: str | None
    period: ResolvedRange
    comparison_period: ResolvedRange | None
    groupings: tuple[str, ...]
    filters: tuple[FilterSpec, ...]
    exclusions: tuple[FilterSpec, ...]
    execution_source: ExecutionSource
    cache_coverage: str | None
    freshness: Mapping[str, Any]
    limitations: tuple[str, ...]
    generated_sql: str | None
    bindings: Mapping[str, Any]
    source_manifests: tuple[SourceManifestRef, ...]
    schema_fingerprints: tuple[str, ...]
    provenance_records: tuple[str, ...]
    s3_bytes_read: int | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "metric": self.metric,
            "cost_basis": dict(self.cost_basis),
            "formula_id": self.formula_id,
            "formula_version": self.formula_version,
            "period": self.period.to_dict(),
            "comparison_period": (
                self.comparison_period.to_dict() if self.comparison_period else None
            ),
            "groupings": list(self.groupings),
            "filters": [item.to_dict() for item in self.filters],
            "exclusions": [item.to_dict() for item in self.exclusions],
            "execution_source": self.execution_source.value,
            "cache_coverage": self.cache_coverage,
            "freshness": dict(self.freshness),
            "limitations": list(self.limitations),
            "generated_sql": self.generated_sql,
            "bindings": dict(self.bindings),
            "source_manifests": [item.to_dict() for item in self.source_manifests],
            "schema_fingerprints": list(self.schema_fingerprints),
            "provenance_records": list(self.provenance_records),
            "s3_bytes_read": self.s3_bytes_read,
        }


@dataclass(frozen=True)
class QueryResult:
    """Renderer-neutral result envelope; PR 0 validates shape only."""

    query: QuerySpec
    period: ResolvedRange
    execution_source: ExecutionSource
    schema_version: str = QUERY_RESULT_VERSION
    comparison_period: ResolvedRange | None = None
    columns: tuple[ColumnDefinition, ...] = ()
    rows: tuple[Mapping[str, Any], ...] = ()
    totals: Mapping[str, Any] = field(default_factory=dict)
    comparison_totals: Mapping[str, Any] | None = None
    deltas: Mapping[str, Any] | None = None
    new_groups: tuple[Mapping[str, Any], ...] = ()
    disappeared_groups: tuple[Mapping[str, Any], ...] = ()
    cost_basis: Mapping[str, Any] = field(default_factory=dict)
    formula_id: str | None = None
    formula_version: str | None = None
    source_manifests: tuple[SourceManifestRef, ...] = ()
    cache_partitions: tuple[str, ...] = ()
    freshness: Mapping[str, Any] = field(default_factory=dict)
    provisional: bool = True
    limitations: tuple[str, ...] = ()
    generated_sql: str | None = None
    bindings: Mapping[str, Any] = field(default_factory=dict)
    rows_scanned: int | None = None
    rows_returned: int | None = None
    s3_bytes_read: int | None = None
    execution_duration_ms: int | None = None
    display_metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.schema_version != QUERY_RESULT_VERSION:
            raise ReckonerContractError(
                f"Unsupported QueryResult schema_version {self.schema_version!r}"
            )
        for name in (
            "rows_scanned",
            "rows_returned",
            "s3_bytes_read",
            "execution_duration_ms",
        ):
            value = getattr(self, name)
            if value is not None and value < 0:
                raise ReckonerContractError(f"{name} cannot be negative")
        if self.rows_returned is not None and self.rows_returned != len(self.rows):
            raise ReckonerContractError("rows_returned must match the serialized row count")

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "query": self.query.to_dict(),
            "period": self.period.to_dict(),
            "comparison_period": (
                self.comparison_period.to_dict() if self.comparison_period else None
            ),
            "columns": [item.to_dict() for item in self.columns],
            "rows": [dict(item) for item in self.rows],
            "totals": dict(self.totals),
            "comparison_totals": (
                dict(self.comparison_totals) if self.comparison_totals is not None else None
            ),
            "deltas": dict(self.deltas) if self.deltas is not None else None,
            "new_groups": [dict(item) for item in self.new_groups],
            "disappeared_groups": [dict(item) for item in self.disappeared_groups],
            "cost_basis": dict(self.cost_basis),
            "formula_id": self.formula_id,
            "formula_version": self.formula_version,
            "source_manifests": [item.to_dict() for item in self.source_manifests],
            "execution_source": self.execution_source.value,
            "cache_partitions": list(self.cache_partitions),
            "freshness": dict(self.freshness),
            "provisional": self.provisional,
            "limitations": list(self.limitations),
            "generated_sql": self.generated_sql,
            "bindings": dict(self.bindings),
            "rows_scanned": self.rows_scanned,
            "rows_returned": self.rows_returned,
            "s3_bytes_read": self.s3_bytes_read,
            "execution_duration_ms": self.execution_duration_ms,
            "display_metadata": dict(self.display_metadata),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> QueryResult:
        allowed = {
            "schema_version",
            "query",
            "period",
            "comparison_period",
            "columns",
            "rows",
            "totals",
            "comparison_totals",
            "deltas",
            "new_groups",
            "disappeared_groups",
            "cost_basis",
            "formula_id",
            "formula_version",
            "source_manifests",
            "execution_source",
            "cache_partitions",
            "freshness",
            "provisional",
            "limitations",
            "generated_sql",
            "bindings",
            "rows_scanned",
            "rows_returned",
            "s3_bytes_read",
            "execution_duration_ms",
            "display_metadata",
        }
        _strict_mapping(data, allowed, "QueryResult")
        query = data.get("query")
        period = data.get("period")
        if not isinstance(query, Mapping) or not isinstance(period, Mapping):
            raise ReckonerContractError("QueryResult requires query and period objects")
        comparison = data.get("comparison_period")
        return cls(
            schema_version=str(data.get("schema_version", "")),
            query=QuerySpec.from_dict(query),
            period=ResolvedRange.from_dict(period),
            comparison_period=(
                ResolvedRange.from_dict(comparison) if isinstance(comparison, Mapping) else None
            ),
            columns=tuple(ColumnDefinition.from_dict(item) for item in data.get("columns", [])),
            rows=tuple(dict(item) for item in data.get("rows", [])),
            totals=dict(data.get("totals", {})),
            comparison_totals=(
                dict(data["comparison_totals"])
                if data.get("comparison_totals") is not None
                else None
            ),
            deltas=dict(data["deltas"]) if data.get("deltas") is not None else None,
            new_groups=tuple(dict(item) for item in data.get("new_groups", [])),
            disappeared_groups=tuple(dict(item) for item in data.get("disappeared_groups", [])),
            cost_basis=dict(data.get("cost_basis", {})),
            formula_id=data.get("formula_id"),
            formula_version=data.get("formula_version"),
            source_manifests=tuple(
                SourceManifestRef.from_dict(item) for item in data.get("source_manifests", [])
            ),
            execution_source=_enum(
                ExecutionSource, data.get("execution_source"), "execution_source"
            ),  # type: ignore[arg-type]
            cache_partitions=tuple(str(item) for item in data.get("cache_partitions", [])),
            freshness=dict(data.get("freshness", {})),
            provisional=bool(data.get("provisional", True)),
            limitations=tuple(str(item) for item in data.get("limitations", [])),
            generated_sql=data.get("generated_sql"),
            bindings=dict(data.get("bindings", {})),
            rows_scanned=data.get("rows_scanned"),
            rows_returned=data.get("rows_returned"),
            s3_bytes_read=data.get("s3_bytes_read"),
            execution_duration_ms=data.get("execution_duration_ms"),
            display_metadata=dict(data.get("display_metadata", {})),
        )
