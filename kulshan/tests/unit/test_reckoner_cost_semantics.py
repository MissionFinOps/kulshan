"""Behavioural tests for canonical AWS cost semantics."""

from __future__ import annotations

from pathlib import Path

import duckdb
import pytest

from kulshan.reckoner.cost import (
    FORMULAS,
    ParquetSource,
    SourceSchemaType,
    build_canonical_relation,
    detect_source_schema,
    evaluate_metric,
)
from kulshan.reckoner.cost.errors import (
    AmbiguousSchemaError,
    MetricUnavailableError,
    MissingCurrencyError,
    MixedCurrencyError,
    UnsupportedSchemaError,
)
from kulshan.reckoner.registries import METRICS, ImplementationStatus

CUR_COLUMNS = [
    "line_item_usage_start_date",
    "line_item_usage_end_date",
    "line_item_line_item_type",
    "line_item_currency_code",
    "line_item_unblended_cost",
    "line_item_net_unblended_cost",
    "line_item_blended_cost",
    "pricing_public_on_demand_cost",
    "line_item_usage_amount",
    "product_product_name",
    "bill_billing_entity",
    "line_item_line_item_description",
    "reservation_reservation_a_r_n",
    "reservation_effective_cost",
    "reservation_unused_amortized_upfront_fee_for_billing_period",
    "reservation_unused_recurring_fee",
    "savings_plan_savings_plan_a_r_n",
    "savings_plan_savings_plan_effective_cost",
    "savings_plan_total_commitment_to_date",
    "savings_plan_used_commitment",
]


def _write_cur(path: Path, *, currencies: tuple[str | None, ...] = ("CAD",)) -> None:
    con = duckdb.connect()
    try:
        rows = [
            ("Usage", 10.0, None, None, None, None, None),
            ("Credit", -2.0, None, None, None, None, None),
            ("Refund", -1.0, None, None, None, None, None),
            ("Tax", 1.0, None, None, None, None, None),
            ("SavingsPlanCoveredUsage", 0.0, None, None, "sp", 6.0, None),
            ("SavingsPlanRecurringFee", 10.0, None, None, "sp", None, (10.0, 7.0)),
            ("DiscountedUsage", 0.0, "ri", 4.0, None, None, None),
            ("RIFee", 8.0, "ri", None, None, None, None),
            ("Fee", 3.0, None, None, None, None, None),
            ("Fee", 5.0, None, None, None, None, None),
        ]
        values = []
        for index, (kind, cost, ri, ri_effective, sp, sp_effective, commitment) in enumerate(rows):
            currency = currencies[index % len(currencies)]
            total, used = commitment or (None, None)
            values.append(
                (
                    "2026-01-01 00:00:00",
                    "2026-01-02 00:00:00",
                    kind,
                    currency,
                    cost,
                    cost - 0.5,
                    cost + 0.25,
                    abs(cost) * 2,
                    1.0,
                    "AWS Support" if index == 8 else "Amazon EC2",
                    "AWS Marketplace" if index == 9 else "AWS",
                    "support" if index == 8 else "line",
                    ri,
                    ri_effective,
                    1.0 if kind == "RIFee" else 0.0,
                    2.0 if kind == "RIFee" else 0.0,
                    sp,
                    sp_effective,
                    total,
                    used,
                )
            )
        placeholders = ",".join("?" for _ in CUR_COLUMNS)
        con.execute(
            "CREATE TABLE source AS SELECT * FROM (VALUES "
            + ",".join(f"({placeholders})" for _ in values)
            + ") AS v("
            + ",".join(f'"{name}"' for name in CUR_COLUMNS)
            + ")",
            [item for row in values for item in row],
        )
        con.execute("COPY source TO ? (FORMAT PARQUET)", [str(path)])
    finally:
        con.close()


def _relation(path: Path, *, source_kind: str = "local"):
    con = duckdb.connect()
    source = ParquetSource(
        (str(path),),
        source_kind=source_kind,
        manifest_id="fixture-manifest" if source_kind == "s3" else None,
    )
    return con, build_canonical_relation(con, source)


def test_schema_detection_is_deterministic_and_versioned() -> None:
    legacy = detect_source_schema(CUR_COLUMNS)
    assert legacy.source_type is SourceSchemaType.LEGACY_CUR
    cur2 = detect_source_schema([*CUR_COLUMNS, "bill_payer_account_name"])
    assert cur2.source_type is SourceSchemaType.CUR_2
    focus = detect_source_schema(
        [
            "BillingPeriodStart",
            "BillingPeriodEnd",
            "ChargePeriodStart",
            "BillingCurrency",
            "BilledCost",
            "EffectiveCost",
            "ChargeCategory",
        ]
    )
    assert (focus.source_type, focus.source_version) == (
        SourceSchemaType.FOCUS_1_0_AWS,
        "1.0",
    )
    with pytest.raises(UnsupportedSchemaError):
        detect_source_schema(["random"])
    with pytest.raises(AmbiguousSchemaError):
        detect_source_schema(
            [
                *CUR_COLUMNS,
                "BillingPeriodStart",
                "BillingPeriodEnd",
                "ChargePeriodStart",
                "BillingCurrency",
                "BilledCost",
                "EffectiveCost",
                "ChargeCategory",
            ]
        )


def test_golden_cost_formulas_and_classification(tmp_path: Path) -> None:
    path = tmp_path / "legacy.parquet"
    _write_cur(path)
    con, relation = _relation(path)
    try:
        assert evaluate_metric(con, relation, "unblended-cost").total == 34
        assert evaluate_metric(con, relation, "net-unblended-cost").total == 29
        assert evaluate_metric(con, relation, "credits").total == -2
        assert evaluate_metric(con, relation, "refunds").total == -1
        assert evaluate_metric(con, relation, "taxes").total == 1
        assert evaluate_metric(con, relation, "blended-cost").total == 36.5
        assert evaluate_metric(con, relation, "public-on-demand-cost").total == 80
        assert evaluate_metric(con, relation, "support").total == 3
        assert evaluate_metric(con, relation, "savings-plan-fees").total == 10
        assert evaluate_metric(con, relation, "reserved-instance-fees").total == 8
        assert evaluate_metric(con, relation, "usage-quantity").total == 10
        amortized = evaluate_metric(con, relation, "amortized-cost")
        assert amortized.total == 32
        assert (amortized.formula_id, amortized.formula_version, amortized.currency) == (
            "kulshan.amortized-cost",
            "1.0",
            "CAD",
        )
        categories = dict(
            con.execute("SELECT raw_line_item_type, charge_category FROM reckoner_cost").fetchall()
        )
        assert categories["Credit"] == "credit"
        assert categories["SavingsPlanCoveredUsage"] == "savings-plan-covered-usage"
        assert categories["DiscountedUsage"] == "reserved-instance-discounted-usage"
        assert "marketplace" in categories.values()
    finally:
        con.close()


def test_explicit_metric_never_falls_back_but_auto_discloses(tmp_path: Path) -> None:
    path = tmp_path / "minimal.parquet"
    _write_cur(path)
    con, relation = _relation(path)
    try:
        with pytest.raises(MetricUnavailableError):
            evaluate_metric(con, relation, "effective-cost")
        auto = evaluate_metric(con, relation, "auto")
        assert auto.metric_id == "amortized-cost"
        assert auto.auto_selection is not None
        assert auto.auto_selection.fallback_order == (
            "amortized-cost",
            "net-unblended-cost",
            "unblended-cost",
        )
    finally:
        con.close()


def test_currency_is_preserved_and_never_converted(tmp_path: Path) -> None:
    mixed = tmp_path / "mixed.parquet"
    _write_cur(mixed, currencies=("CAD", "USD"))
    con, relation = _relation(mixed)
    try:
        with pytest.raises(MixedCurrencyError):
            evaluate_metric(con, relation, "unblended-cost")
        separated = evaluate_metric(con, relation, "unblended-cost", groupings=("currency",))
        assert {row["currency"] for row in separated.rows} == {"CAD", "USD"}
        assert separated.currency is None
    finally:
        con.close()
    missing = tmp_path / "missing.parquet"
    _write_cur(missing, currencies=(None,))
    con, relation = _relation(missing)
    try:
        with pytest.raises(MissingCurrencyError):
            evaluate_metric(con, relation, "unblended-cost")
    finally:
        con.close()


def test_local_and_manifest_pinned_s3_use_identical_relation(tmp_path: Path) -> None:
    path = tmp_path / "same.parquet"
    _write_cur(path)
    local_con, local = _relation(path)
    s3_con, s3 = _relation(path, source_kind="s3")
    try:
        local_rows = local_con.execute(
            "SELECT raw_line_item_type, charge_category, amortized_cost, currency "
            "FROM reckoner_cost ORDER BY raw_line_item_type"
        ).fetchall()
        s3_rows = s3_con.execute(
            "SELECT raw_line_item_type, charge_category, amortized_cost, currency "
            "FROM reckoner_cost ORDER BY raw_line_item_type"
        ).fetchall()
        assert local_rows == s3_rows
        assert evaluate_metric(local_con, local, "amortized-cost") == evaluate_metric(
            s3_con, s3, "amortized-cost"
        )
    finally:
        local_con.close()
        s3_con.close()


def test_registry_exposes_only_qualified_implementations() -> None:
    assert set(FORMULAS) == {
        metric_id
        for metric_id, descriptor in METRICS.items()
        if descriptor.implementation_status is ImplementationStatus.AVAILABLE
    }
    assert METRICS["invoiced-cost"].implementation_status is ImplementationStatus.UNAVAILABLE
    assert METRICS["net-amortized-cost"].implementation_status is ImplementationStatus.UNAVAILABLE
    assert (
        METRICS["unused-commitment-cost"].implementation_status is ImplementationStatus.UNAVAILABLE
    )


def test_s3_context_propagates_session_and_closes(monkeypatch: pytest.MonkeyPatch) -> None:
    import kulshan.cur.s3_query as s3_query
    import kulshan.reckoner.cost.semantics as semantics

    class FakeConnection:
        closed = False

        def close(self) -> None:
            self.closed = True

    connection = FakeConnection()
    seen: dict[str, object] = {}

    def connect_s3_duckdb(*, session: object, region: str | None):
        seen.update(session=session, region=region)
        return connection

    schema = detect_source_schema(CUR_COLUMNS)
    expected = semantics.CanonicalRelation("test", schema, "s3")
    monkeypatch.setattr(s3_query, "connect_s3_duckdb", connect_s3_duckdb)
    monkeypatch.setattr(semantics, "build_canonical_relation", lambda *args: expected)
    session = object()
    source = ParquetSource(
        ("s3://bucket/exact.parquet",),
        source_kind="s3",
        manifest_id="manifest-1",
        region="ca-central-1",
    )
    with semantics.open_s3_relation(source, session=session) as (_, relation):
        assert relation is expected
    assert seen == {"session": session, "region": "ca-central-1"}
    assert connection.closed is True


def test_focus_1_0_effective_cost_is_not_an_amortized_alias(tmp_path: Path) -> None:
    path = tmp_path / "focus.parquet"
    con = duckdb.connect()
    try:
        con.execute(
            """
            CREATE TABLE focus AS SELECT * FROM (VALUES
              (TIMESTAMP '2026-01-01', TIMESTAMP '2026-02-01',
               TIMESTAMP '2026-01-02', TIMESTAMP '2026-01-03',
               'CAD', 9.0, 7.0, 12.0, 'Usage', 'Regular', 2.0, 'Amazon EC2')
            ) AS v(
              BillingPeriodStart, BillingPeriodEnd, ChargePeriodStart,
              ChargePeriodEnd, BillingCurrency, BilledCost, EffectiveCost,
              ListCost, ChargeCategory, ChargeClass, ConsumedQuantity, ServiceName
            )
            """
        )
        con.execute("COPY focus TO ? (FORMAT PARQUET)", [str(path)])
        relation = build_canonical_relation(con, ParquetSource((str(path),)))
        assert evaluate_metric(con, relation, "effective-cost").total == 7
        assert evaluate_metric(con, relation, "unblended-cost").total == 9
        with pytest.raises(MetricUnavailableError):
            evaluate_metric(con, relation, "amortized-cost")
    finally:
        con.close()
