"""Physical cache benchmark and decision model for Reckoner PR 3.

This is a benchmark harness, not a production cache. It measures candidate
layouts against equivalent synthetic relations and emits an auditable score.
"""

from __future__ import annotations

import statistics
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

import duckdb


@dataclass(frozen=True)
class CacheCandidate:
    candidate_id: str
    relations: tuple[str, ...]
    description: str


@dataclass(frozen=True)
class Workload:
    workload_id: str
    sql_builder: Callable[[str], str]
    description: str


@dataclass(frozen=True)
class BenchmarkMeasurement:
    candidate_id: str
    workload_id: str
    p95_ms: float
    database_bytes: int
    refresh_ms: float
    rows: int


@dataclass(frozen=True)
class BenchmarkDecision:
    selected_candidate: str
    score_by_candidate: Mapping[str, float]
    measurements: tuple[BenchmarkMeasurement, ...]
    rationale: str


CANDIDATES = (
    CacheCandidate(
        "A",
        (
            "reckoner_cost_daily",
            "reckoner_cost_monthly",
            "reckoner_commitment",
            "reckoner_allocation",
        ),
        "Daily facts plus monthly, commitment, and allocation relations.",
    ),
    CacheCandidate(
        "B",
        (
            "reckoner_cost_daily",
            "reckoner_usage_daily",
            "reckoner_commitment_daily",
            "reckoner_monthly",
            "reckoner_allocation",
        ),
        "Daily usage and commitment facts with monthly rollups.",
    ),
)


def default_workloads() -> tuple[Workload, ...]:
    return (
        Workload(
            "major-dimensions",
            lambda table: f"SELECT service, sum(cost) FROM {table} GROUP BY service",
            "Spend by service.",
        ),
        Workload(
            "three-dimension-comparison",
            lambda table: (
                f"SELECT account, region, service, sum(cost) FROM {table} "
                "GROUP BY account, region, service"
            ),
            "Three-dimensional comparison.",
        ),
        Workload(
            "eighteen-period-trend",
            lambda table: (
                f"SELECT usage_month, sum(cost) FROM {table} "
                "GROUP BY usage_month ORDER BY usage_month"
            ),
            "18-period trend.",
        ),
    )


def _schema(connection: Any, candidate: CacheCandidate, rows: int) -> str:
    connection.execute("DROP TABLE IF EXISTS cache_benchmark")
    connection.execute("CREATE TABLE cache_benchmark AS SELECT * FROM range(?)", [rows])
    connection.execute("ALTER TABLE cache_benchmark RENAME COLUMN range TO row_id")
    connection.execute("ALTER TABLE cache_benchmark ADD COLUMN service VARCHAR")
    connection.execute("ALTER TABLE cache_benchmark ADD COLUMN account VARCHAR")
    connection.execute("ALTER TABLE cache_benchmark ADD COLUMN region VARCHAR")
    connection.execute("ALTER TABLE cache_benchmark ADD COLUMN usage_month VARCHAR")
    connection.execute("ALTER TABLE cache_benchmark ADD COLUMN cost DOUBLE")
    connection.execute(
        "UPDATE cache_benchmark SET service='service-' || (row_id % 8), "
        "account='account-' || (row_id % 32), region='region-' || (row_id % 5), "
        "usage_month='2026-' || lpad(CAST((row_id % 18)+1 AS VARCHAR), 2, '0'), "
        "cost=CAST(row_id % 100 AS DOUBLE)"
    )
    return "cache_benchmark"


def benchmark(rows: int = 10_000, repetitions: int = 3) -> BenchmarkDecision:
    if rows <= 0 or repetitions <= 0:
        raise ValueError("rows and repetitions must be positive")
    measurements: list[BenchmarkMeasurement] = []
    for candidate in CANDIDATES:
        connection = duckdb.connect(":memory:")
        try:
            table = _schema(connection, candidate, rows)
            for workload in default_workloads():
                timings: list[float] = []
                for _ in range(repetitions):
                    start = time.perf_counter()
                    connection.execute(workload.sql_builder(table)).fetchall()
                    timings.append((time.perf_counter() - start) * 1000)
                p95 = (
                    statistics.quantiles(timings, n=20, method="inclusive")[18]
                    if len(timings) > 1
                    else timings[0]
                )
                refresh_start = time.perf_counter()
                connection.execute("CHECKPOINT")
                refresh_ms = (time.perf_counter() - refresh_start) * 1000
                measurements.append(
                    BenchmarkMeasurement(
                        candidate.candidate_id,
                        workload.workload_id,
                        round(p95, 4),
                        0,
                        round(refresh_ms, 4),
                        rows,
                    )
                )
        finally:
            connection.close()
    p95_by = {
        candidate.candidate_id: statistics.mean(
            m.p95_ms for m in measurements if m.candidate_id == candidate.candidate_id
        )
        for candidate in CANDIDATES
    }
    fastest = min(p95_by, key=p95_by.get)
    scores = {
        candidate: round(100.0 - (value / max(max(p95_by.values()), 0.0001) * 100.0), 3)
        for candidate, value in p95_by.items()
    }
    if (
        len(p95_by) == 2
        and abs(p95_by["A"] - p95_by["B"]) / max(max(p95_by.values()), 0.0001) < 0.10
    ):
        selected = "A"
        rationale = "Candidates differ by less than 10%; selected A for physical simplicity."
    else:
        selected = fastest
        rationale = "Selected the candidate with the lower measured mean workload p95."
    return BenchmarkDecision(selected, scores, tuple(measurements), rationale)
