"""Synthetic bounded-batch validation; this is not an enterprise benchmark."""

import duckdb

from kulshan.export.batching import populate_alias_map
from kulshan.pseudonym.engine import PseudonymizationEngine
from kulshan.pseudonym.policy import PseudonymPolicy
from kulshan.pseudonym.types import IdentifierClass


def test_alias_map_10000_distinct_rows():
    con = duckdb.connect()
    try:
        con.execute("CREATE VIEW source AS SELECT 'project-' || range AS value FROM range(10000)")
        engine = PseudonymizationEngine(b"x" * 32, PseudonymPolicy.for_persistence())
        populate_alias_map(
            con,
            "aliases",
            "SELECT value FROM source",
            engine,
            IdentifierClass.UNKNOWN,
            batch_size=127,
        )
        assert con.execute("SELECT count(*), count(DISTINCT alias) FROM aliases").fetchone() == (
            10000,
            10000,
        )
        assert (
            con.execute("SELECT count(*) FROM aliases WHERE raw_value = alias").fetchone()[0] == 0
        )
    finally:
        con.close()


def test_missing_efficiency_inputs_are_unknown():
    import pandas as pd

    from kulshan.checks.cost.analyzers.efficiency import compute_efficiency_score

    empty = pd.DataFrame()
    score = compute_efficiency_score(empty, empty, empty, empty, empty, 100)
    assert score["total_score"] is None
    assert score["grade"] == "N/A"
    assert all(item["value"] == "unknown" for item in score["breakdown"].values())


def test_commitments_are_not_stability_and_low_cost_is_not_idle():
    import pandas as pd

    from kulshan.checks.cost.analyzers.efficiency import compute_efficiency_score
    from kulshan.checks.cost.analyzers.waste import detect_idle_services

    empty = pd.DataFrame()
    score = compute_efficiency_score(
        pd.DataFrame({"coverage_pct": [90]}), empty, empty, empty, empty, 100
    )
    assert score["breakdown"]["cost_stability"]["value"] == "unknown"
    candidate = detect_idle_services(pd.DataFrame({"service": ["EC2"], "cost": [0.1]}), "service")
    assert candidate.iloc[0]["idle_status"] == "unknown"
