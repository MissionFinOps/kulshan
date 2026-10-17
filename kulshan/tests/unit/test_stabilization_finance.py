"""Period, currency and total regressions using synthetic offline data."""

from datetime import datetime

import duckdb
import pytest

from kulshan.reckoner.contracts import PeriodSpec, QuerySpec
from kulshan.reckoner.cost import ParquetSource, build_canonical_relation
from kulshan.reckoner.cost.errors import MissingCurrencyError, MixedCurrencyError
from kulshan.reckoner.query import execute_query


def relation_for(tmp_path, currencies=("CAD", "CAD")):
    con = duckdb.connect()
    con.execute(
        "CREATE TABLE data(line_item_usage_start_date TIMESTAMP, "
        "line_item_line_item_type VARCHAR, line_item_currency_code VARCHAR, "
        "line_item_unblended_cost DOUBLE, product_product_name VARCHAR)"
    )
    con.executemany(
        "INSERT INTO data VALUES (?, 'Usage', ?, ?, ?)",
        [
            ("2025-12-01", currencies[0], 10, "EC2"),
            ("2026-01-02", currencies[1], 20, "S3"),
        ],
    )
    path = tmp_path / "data.parquet"
    con.execute("COPY data TO ? (FORMAT PARQUET)", [str(path)])
    return con, build_canonical_relation(con, ParquetSource((str(path),)))


def test_total_does_not_depend_on_limit(tmp_path):
    con, relation = relation_for(tmp_path)
    try:
        result = execute_query(
            con,
            relation,
            QuerySpec(
                metric="unblended-cost",
                period=PeriodSpec("custom", "2025-12-01", "2026-02-01"),
                groupings=("service",),
                limit=1,
            ),
        )
        assert len(result.rows) == 1
        assert result.totals["value"] == 30
        assert result.cost_basis["currency"] == "CAD"
    finally:
        con.close()


@pytest.mark.parametrize(
    "currencies,error",
    [(("CAD", "USD"), MixedCurrencyError), (("CAD", None), MissingCurrencyError)],
)
def test_executor_enforces_currency(tmp_path, currencies, error):
    con, relation = relation_for(tmp_path, currencies)
    try:
        with pytest.raises(error):
            execute_query(
                con,
                relation,
                QuerySpec(
                    metric="unblended-cost", period=PeriodSpec("custom", "2025-12-01", "2026-02-01")
                ),
            )
    finally:
        con.close()


def test_grouped_currency_has_no_cross_currency_total(tmp_path):
    con, relation = relation_for(tmp_path, ("CAD", "USD"))
    try:
        result = execute_query(
            con,
            relation,
            QuerySpec(
                metric="unblended-cost",
                period=PeriodSpec("custom", "2025-12-01", "2026-02-01"),
                groupings=("currency",),
            ),
        )
        assert result.totals == {"CAD": 10, "USD": 20}
        from kulshan.reckoner.terminal import render_result
        text = render_result(result, mode="compact")
        assert "CAD 10.00" in text
        assert "USD 20.00" in text
    finally:
        con.close()


def test_current_and_latest_are_distinct(tmp_path, monkeypatch):
    import kulshan.reckoner.query as module

    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return cls(2026, 10, 16)

    monkeypatch.setattr(module, "datetime", Clock)
    con, relation = relation_for(tmp_path)
    try:
        current = execute_query(
            con,
            relation,
            QuerySpec(metric="unblended-cost", period=PeriodSpec("current-billing-period")),
        )
        latest = execute_query(
            con,
            relation,
            QuerySpec(
                metric="unblended-cost", period=PeriodSpec("latest-available-billing-period")
            ),
        )
        assert current.period.start.startswith("2026-10-01")
        assert current.totals["value"] == 0
        assert latest.period.start.startswith("2026-01-01")
        assert latest.totals["value"] == 20
    finally:
        con.close()
