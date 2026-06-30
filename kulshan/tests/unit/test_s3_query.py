# ruff: noqa: E501
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from kulshan.cur.errors import CurDataError
from kulshan.cur.manifest_reader import ManifestFile, ManifestIndex
from kulshan.cur.s3_query import (
    connect_s3_duckdb,
    estimate_scan_bytes,
    select_cost_column,
)


def _manifest() -> ManifestIndex:
    return ManifestIndex(
        bucket="bucket",
        prefix="export/",
        billing_period="2026-06",
        export_name="export",
        files=(ManifestFile("export/data/BILLING_PERIOD=2026-06/a.parquet", 100),),
        columns=(),
        total_size_bytes=100,
        s3_glob="s3://bucket/export/data/BILLING_PERIOD=2026-06/a.parquet",
        manifest_key="export/metadata/Manifest.json",
        manifest_size_bytes=1,
    )


class FakeCon:
    def __init__(self, responses: list[object] | None = None, fail_metadata: bool = False) -> None:
        self.sql: list[str] = []
        self.responses = responses or []
        self.fail_metadata = fail_metadata

    def execute(self, sql: str):
        self.sql.append(sql)
        if self.fail_metadata and "parquet_metadata" in sql:
            raise RuntimeError("metadata unavailable")
        return self

    def fetchone(self):
        if self.responses:
            return self.responses.pop(0)
        return [0]

    def fetchall(self):
        return []

    def close(self) -> None:
        self.sql.append("close")


def test_connect_s3_duckdb_uses_aws_credential_chain(monkeypatch: pytest.MonkeyPatch) -> None:
    con = FakeCon()
    duckdb = MagicMock()
    duckdb.connect.return_value = con
    monkeypatch.setitem(__import__("sys").modules, "duckdb", duckdb)
    monkeypatch.setattr(
        "kulshan.cur.s3_query.boto3.session.Session", lambda: MagicMock(region_name="ca-central-1")
    )

    connect_s3_duckdb()

    joined = "\n".join(con.sql)
    assert "LOAD httpfs" in joined
    assert "CREATE TEMPORARY SECRET" in joined
    assert "PROVIDER credential_chain" in joined
    assert "ca-central-1" in joined


def test_connect_s3_duckdb_uses_temporary_secret_only(monkeypatch: pytest.MonkeyPatch) -> None:
    con = FakeCon()
    duckdb = MagicMock()
    duckdb.connect.return_value = con
    monkeypatch.setitem(__import__("sys").modules, "duckdb", duckdb)
    monkeypatch.setattr(
        "kulshan.cur.s3_query.boto3.session.Session", lambda: MagicMock(region_name=None)
    )

    connect_s3_duckdb()

    sql = "\n".join(con.sql).upper()
    assert "CREATE TEMPORARY SECRET" in sql
    assert "CREATE PERSISTENT SECRET" not in sql
    assert "AWS_ACCESS_KEY_ID" not in sql
    assert "AWS_SECRET_ACCESS_KEY" not in sql


def test_connect_s3_duckdb_httpfs_load_failure_is_clear(monkeypatch: pytest.MonkeyPatch) -> None:
    class FailingCon(FakeCon):
        def execute(self, sql: str):
            if sql == "LOAD httpfs":
                raise RuntimeError("missing")
            return super().execute(sql)

    duckdb = MagicMock()
    duckdb.connect.return_value = FailingCon()
    monkeypatch.setitem(__import__("sys").modules, "duckdb", duckdb)

    with pytest.raises(CurDataError, match="DuckDB httpfs is required"):
        connect_s3_duckdb()


def test_estimate_uses_parquet_file_metadata_for_sanity_and_parquet_metadata_for_columns() -> None:
    con = FakeCon(responses=[[55]])

    estimate = estimate_scan_bytes(con, _manifest(), ("line_item_unblended_cost",))

    sql = "\n".join(con.sql)
    assert "parquet_file_metadata" in sql
    assert "parquet_metadata" in sql
    assert "path_in_schema" in sql
    assert "total_compressed_size" in sql
    assert estimate.estimated_bytes == 55
    assert estimate.method == "parquet_metadata"


def test_estimate_falls_back_to_upper_bound_if_metadata_fails() -> None:
    con = FakeCon(fail_metadata=True)

    estimate = estimate_scan_bytes(con, _manifest(), ("line_item_unblended_cost",))

    assert estimate.estimated_bytes == 100
    assert estimate.method == "manifest_upper_bound"


def test_select_cost_column_falls_back_when_net_unblended_is_null() -> None:
    con = FakeCon(responses=[[0], [2]])

    selection = select_cost_column(
        con,
        _manifest(),
        {"line_item_net_unblended_cost", "line_item_unblended_cost", "line_item_usage_start_date"},
        "2026-06",
    )

    assert selection.column == "line_item_unblended_cost"
    assert "line_item_net_unblended_cost was null" in selection.fallback_note


def test_select_cost_column_all_null_gives_clear_error() -> None:
    con = FakeCon(responses=[[0], [0]])

    with pytest.raises(CurDataError, match="all null"):
        select_cost_column(
            con,
            _manifest(),
            {"line_item_net_unblended_cost", "line_item_unblended_cost"},
            "2026-06",
        )


def test_generated_sql_uses_hive_partitioning_true() -> None:
    con = FakeCon(responses=[[1]])

    select_cost_column(con, _manifest(), {"line_item_unblended_cost"})

    assert "hive_partitioning=true" in "\n".join(con.sql)
