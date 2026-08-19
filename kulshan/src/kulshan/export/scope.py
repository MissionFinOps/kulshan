"""EvidenceScope: single immutable scope object shared by CUR and CE export paths."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Optional


@dataclass(frozen=True)
class EvidenceScope:
    """Defines the data boundary for a consultant evidence export.

    Both CUR extraction and every CE API call compile their filters from
    this same object. Prevents scope mismatch.
    """

    from_date: date
    to_date: date
    include_accounts: tuple[str, ...] = ()
    exclude_accounts: tuple[str, ...] = ()
    include_services: tuple[str, ...] = ()
    exclude_services: tuple[str, ...] = ()

    def __post_init__(self):
        if self.include_accounts and self.exclude_accounts:
            raise ValueError("Cannot specify both include_accounts and exclude_accounts")
        if self.include_services and self.exclude_services:
            raise ValueError("Cannot specify both include_services and exclude_services")
        if self.from_date >= self.to_date:
            raise ValueError(f"from_date ({self.from_date}) must be before to_date ({self.to_date})")

    def to_dict(self) -> dict:
        """Serialize for manifest.json."""
        return {
            "from_date": self.from_date.isoformat(),
            "to_date": self.to_date.isoformat(),
            "include_accounts": list(self.include_accounts),
            "exclude_accounts": list(self.exclude_accounts),
            "include_services": list(self.include_services),
            "exclude_services": list(self.exclude_services),
        }

    def duckdb_where_clause(self, date_col: str, account_col: Optional[str], service_col: str) -> str:
        """Build a DuckDB WHERE clause from this scope."""
        clauses = []
        clauses.append(
            f"CAST({date_col} AS DATE) >= '{self.from_date.isoformat()}'"
        )
        clauses.append(
            f"CAST({date_col} AS DATE) < '{self.to_date.isoformat()}'"
        )
        if self.include_accounts and account_col:
            vals = ", ".join(f"'{a}'" for a in self.include_accounts)
            clauses.append(f"CAST({account_col} AS VARCHAR) IN ({vals})")
        elif self.exclude_accounts and account_col:
            vals = ", ".join(f"'{a}'" for a in self.exclude_accounts)
            clauses.append(f"CAST({account_col} AS VARCHAR) NOT IN ({vals})")
        if self.include_services:
            vals = ", ".join(f"'{s}'" for s in self.include_services)
            clauses.append(f"CAST({service_col} AS VARCHAR) IN ({vals})")
        elif self.exclude_services:
            vals = ", ".join(f"'{s}'" for s in self.exclude_services)
            clauses.append(f"CAST({service_col} AS VARCHAR) NOT IN ({vals})")
        return " AND ".join(clauses)

    def ce_filter(self) -> dict | None:
        """Build a Cost Explorer Filter dict, or None if no filtering needed."""
        filters = []
        if self.include_accounts:
            filters.append({"Dimensions": {"Key": "LINKED_ACCOUNT", "Values": list(self.include_accounts)}})
        elif self.exclude_accounts:
            filters.append({"Not": {"Dimensions": {"Key": "LINKED_ACCOUNT", "Values": list(self.exclude_accounts)}}})
        if self.include_services:
            filters.append({"Dimensions": {"Key": "SERVICE", "Values": list(self.include_services)}})
        elif self.exclude_services:
            filters.append({"Not": {"Dimensions": {"Key": "SERVICE", "Values": list(self.exclude_services)}}})
        if not filters:
            return None
        if len(filters) == 1:
            return filters[0]
        return {"And": filters}
