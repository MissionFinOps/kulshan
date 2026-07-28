from kulshan.reckoner.cache.benchmark import CANDIDATES, benchmark, default_workloads


def test_candidates_cover_locked_workloads() -> None:
    assert {candidate.candidate_id for candidate in CANDIDATES} == {"A", "B"}
    assert {workload.workload_id for workload in default_workloads()} == {
        "major-dimensions",
        "three-dimension-comparison",
        "eighteen-period-trend",
    }


def test_benchmark_is_bounded_and_explains_decision() -> None:
    decision = benchmark(rows=100, repetitions=2)
    assert decision.selected_candidate in {"A", "B"}
    assert set(decision.score_by_candidate) == {"A", "B"}
    assert len(decision.measurements) == 6
    assert decision.rationale
