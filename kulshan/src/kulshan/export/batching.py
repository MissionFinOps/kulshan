"""Bound Python memory while building independently derived alias maps."""

from __future__ import annotations

from typing import Any


def populate_alias_map(
    con: Any, table: str, sql: str, engine: Any, kind: Any, batch_size: int = 2048
) -> None:
    """Stream distinct values on a separate cursor while inserting bounded batches."""
    con.execute(f"CREATE TEMP TABLE {table} (raw_value VARCHAR, alias VARCHAR)")
    reader = con.cursor()
    try:
        reader.execute(sql)
        while batch := reader.fetchmany(batch_size):
            mapped = [
                (
                    value,
                    engine.pseudonymize_value(value, kind) if value and value.strip() else value,
                )
                for (value,) in batch
            ]
            con.executemany(f"INSERT INTO {table} VALUES (?, ?)", mapped)
    finally:
        reader.close()
