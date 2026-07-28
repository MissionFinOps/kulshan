"""Structured canonical-cost errors."""


class CostSemanticError(RuntimeError):
    """Base error for canonical cost semantics."""

    code = "cost-semantic-error"


class UnsupportedSchemaError(CostSemanticError):
    code = "unsupported-schema"


class AmbiguousSchemaError(CostSemanticError):
    code = "ambiguous-schema"


class UnsupportedSourceVersionError(CostSemanticError):
    code = "unsupported-source-version"


class MissingRequiredFieldsError(CostSemanticError):
    code = "missing-required-fields"

    def __init__(self, fields: tuple[str, ...]):
        self.fields = fields
        super().__init__("Missing required fields: " + ", ".join(fields))


class IncompatibleColumnTypeError(CostSemanticError):
    code = "incompatible-column-type"


class MetricUnavailableError(CostSemanticError):
    code = "metric-unavailable"

    def __init__(self, metric_id: str, schema: str, missing_fields: tuple[str, ...]):
        self.metric_id = metric_id
        self.schema = schema
        self.missing_fields = missing_fields
        detail = ", ".join(missing_fields) if missing_fields else "unsupported source schema"
        super().__init__(f"Metric {metric_id} is unavailable for {schema}: {detail}")


class MixedCurrencyError(CostSemanticError):
    code = "mixed-currency"


class MissingCurrencyError(CostSemanticError):
    code = "missing-currency"


class InvalidGroupingError(CostSemanticError):
    code = "invalid-grouping"
