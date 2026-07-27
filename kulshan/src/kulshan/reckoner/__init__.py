"""Foundational, renderer-neutral contracts for the future Reckoner Engine.

PR 0 exposes only validated data contracts and registries. It does not execute
queries, calculate costs, or alter existing Kulshan commands.
"""

from kulshan.reckoner.contracts import (
    QUERY_RESULT_VERSION,
    QUERY_SPEC_VERSION,
    QueryResult,
    QuerySpec,
    ReckonerContractError,
)

__all__ = [
    "QUERY_RESULT_VERSION",
    "QUERY_SPEC_VERSION",
    "QueryResult",
    "QuerySpec",
    "ReckonerContractError",
]
