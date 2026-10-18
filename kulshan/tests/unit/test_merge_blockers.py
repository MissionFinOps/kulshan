"""Offline end-to-end regressions for the independent merge audit."""

import json
import zipfile
from copy import deepcopy
from types import SimpleNamespace

import duckdb
import pytest
from click.testing import CliRunner
from rich.console import Console

from kulshan.checks.cost.analyzers.advanced import compute_executive_scorecard
from kulshan.consolidated import _merge_pack_results, run_consolidated_report
from kulshan.orchestrator import scan_exit_code, summarize_completeness


def test_actual_zip_omits_dropped_column_names(tmp_path, monkeypatch):
    from kulshan.export.cli import export

    source = tmp_path / "source.parquet"
    con = duckdb.connect()
    con.execute("""CREATE TABLE source AS SELECT DATE '2026-07-15' AS line_item_usage_start_date,
        '111222333444' AS line_item_usage_account_id, 'AmazonEC2' AS line_item_product_code,
        'BoxUsage' AS line_item_usage_type, 42.50::DECIMAL(12,2) AS line_item_unblended_cost,
        'secret-budget' AS cost_category_project_nightingale""")
    con.execute("COPY source TO ? (FORMAT PARQUET)", [str(source)])
    con.close()
    monkeypatch.setattr(
        "kulshan.pseudonym.context.resolve_workspace_secret_path", lambda: tmp_path / "workspace"
    )
    output = tmp_path / "evidence.zip"
    result = CliRunner().invoke(
        export,
        [
            "consultant",
            str(source),
            "--from",
            "2026-07-01",
            "--to",
            "2026-08-01",
            "-o",
            str(output),
        ],
    )
    assert result.exit_code == 0, result.output
    with zipfile.ZipFile(output) as package:
        for name in package.namelist():
            content = package.read(name)
            if name.endswith(".parquet"):
                extracted = tmp_path / "exported.parquet"
                extracted.write_bytes(content)
                con = duckdb.connect()
                schema = con.execute(
                    "DESCRIBE SELECT * FROM read_parquet(?)", [str(extracted)]
                ).fetchall()
                assert "nightingale" not in str(schema)
                assert (
                    con.execute(
                        "SELECT line_item_unblended_cost FROM read_parquet(?)", [str(extracted)]
                    ).fetchone()[0]
                    == 42.50
                )
                con.close()
            else:
                assert "nightingale" not in content.decode().lower()
                assert "secret-budget" not in content.decode()
        privacy = json.loads(package.read("privacy-report.json"))
        assert all(gate["passed"] for gate in privacy["gates"])


def pack(**updates):
    return {
        "findings": [],
        "scores": {"overall_score": 100, "grade": "A", "total_findings": 0},
        **updates,
    }


@pytest.mark.parametrize(
    "parts,status",
    [
        ([pack(), pack()], "complete"),
        ([pack(), pack(skipped=True, errors=["AccessDenied"])], "partial"),
        ([pack(), pack(errors=["AccessDenied"])], "partial"),
        ([pack(partial=True), pack()], "partial"),
        ([pack(skipped=True), pack(skipped=True)], "unavailable"),
    ],
)
def test_consolidated_coverage(monkeypatch, tmp_path, parts, status):
    monkeypatch.setattr(
        "kulshan.consolidated.create_verified_session",
        lambda **kw: SimpleNamespace(
            session=object(), account_id={"a": "111222333444", "b": "555666777888"}[kw["profile"]]
        ),
    )
    pending = iter(deepcopy(parts))
    monkeypatch.setattr(
        "kulshan.consolidated.run_all_scans", lambda *a, **kw: {"security": next(pending)}
    )
    report = run_consolidated_report(
        [
            {"name": "a", "profile": "a", "expected_session_account_id": "111222333444"},
            {"name": "b", "profile": "b", "expected_session_account_id": "555666777888"},
        ],
        ["us-east-1"],
        ["security"],
        console=Console(quiet=True),
    )
    metadata = summarize_completeness(report.results)
    assert metadata["status"] == status
    assert report.report_status == status
    assert scan_exit_code(report.results) == (0 if status == "complete" else 2)
    merged = report.results["security"]
    assert len(merged["coverage_by_source"]) == 2
    if status != "complete":
        assert merged["scores"]["overall_score"] is None
        assert report.overall_grade == "N/A"
    assert json.loads(json.dumps(metadata))["status"] == status
    from kulshan.cli import report as cli_report

    connections = [
        SimpleNamespace(name=name, profile=name, role_arn=None, expected_session_account_id=account)
        for name, account in (("a", "111222333444"), ("b", "555666777888"))
    ]
    workspace = SimpleNamespace(
        is_bound=True,
        display_name="fixture",
        payer_account_id=None,
        history_db_path=tmp_path / "history.db",
        config=SimpleNamespace(aws=SimpleNamespace(connections=connections, cost_connection=None)),
    )
    monkeypatch.setattr("kulshan.workspace.resolution.resolve_workspace", lambda *_: workspace)
    monkeypatch.setattr("kulshan.consolidated.run_consolidated_report", lambda **kw: report)
    output = tmp_path / "consolidated.json"
    cli = CliRunner().invoke(
        cli_report,
        [
            "--packs",
            "security",
            "--regions",
            "us-east-1",
            "--format",
            "json",
            "--output",
            str(output),
            "--yes",
            "--no-history",
            "--show-identifiers",
        ],
        obj={"workspace": "fixture"},
    )
    assert cli.exit_code == (0 if status == "complete" else 2), cli.output
    emitted = json.loads(output.read_text(encoding="utf-8"))
    assert emitted["scan_metadata"]["report_status"] == status
    assert emitted["scan_metadata"]["status"] == status
    assert emitted["coverage"]["summary"]["report_status"] == status
    if status != "complete":
        assert emitted["overall_score"] is None


def test_failed_connection_keeps_missing_evidence(monkeypatch):
    monkeypatch.setattr(
        "kulshan.consolidated.create_verified_session",
        lambda **kw: SimpleNamespace(session=object(), account_id="111222333444"),
    )
    calls = iter([{"security": pack()}, RuntimeError("connection lost")])

    def scan(*args, **kwargs):
        result = next(calls)
        if isinstance(result, Exception):
            raise result
        return result

    monkeypatch.setattr("kulshan.consolidated.run_all_scans", scan)
    report = run_consolidated_report(
        [
            {"name": name, "profile": name, "expected_session_account_id": "111222333444"}
            for name in ("a", "b")
        ],
        ["us-east-1"],
        ["security"],
        console=Console(quiet=True),
    )
    assert report.report_status == "partial"
    assert report.results["security"]["source_connections"] == ["a", "b"]
    assert report.results["security"]["errors"]
    assert scan_exit_code(report.results) == 2


def test_merge_preserves_source_detail_without_mutating_inputs():
    inputs = [
        pack(metadata={"origin": "a"}, coverage={"region": "us-east-1"}),
        pack(metadata={"origin": "b"}, errors=["AccessDenied"], coverage={"region": "us-west-2"}),
    ]
    before = deepcopy(inputs)
    merged = _merge_pack_results(inputs)
    assert inputs == before
    assert [item["metadata"]["origin"] for item in merged["coverage_by_source"]] == ["a", "b"]
    assert merged["coverage_by_source"][1]["region_coverage"]["region"] == "us-west-2"
    assert merged["errors"] == ["AccessDenied"]


def test_cur_only_cli_failure(tmp_path, monkeypatch):
    from unittest.mock import Mock

    from kulshan.cli import report

    workspace = SimpleNamespace(
        is_bound=False,
        config=SimpleNamespace(aws=None),
        history_db_path=tmp_path / "history.db",
        payer_account_id=None,
    )
    monkeypatch.setattr("kulshan.workspace.resolution.resolve_workspace", lambda *_: workspace)
    monkeypatch.setattr(
        "kulshan.workspace.execution.resolve_aws_execution",
        lambda **kw: SimpleNamespace(session=Mock(), session_account_id="111222333444"),
    )
    export = SimpleNamespace(
        s3_uri="s3://fixture/cur", s3_bucket="fixture", s3_prefix="cur", s3_region="us-east-1"
    )
    monkeypatch.setattr(
        "kulshan.preflight.run_preflight_with_cur",
        lambda *a, **kw: SimpleNamespace(passed=True, cur_export=export, cur_accessible=True),
    )

    def denied(*args, **kwargs):
        raise RuntimeError("AccessDenied")

    monkeypatch.setattr("kulshan.cur.periods.list_manifest_periods", denied)
    output = tmp_path / "report.json"
    result = CliRunner().invoke(
        report,
        [
            "--format",
            "json",
            "--output",
            str(output),
            "--yes",
            "--no-history",
            "--regions",
            "us-east-1",
            "--cost-source",
            "cur",
        ],
        obj={"workspace": "fixture"},
    )
    assert result.exit_code == 2, result.output
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["scan_metadata"]["status"] == "unavailable"
    assert payload["scan_metadata"]["partial"] is True
    assert payload["overall_score"] is None
    assert payload["coverage"]["summary"]["report_status"] == "unavailable"


@pytest.mark.parametrize("fmt", ["json", "html", "terminal"])
def test_partial_report_presentation(tmp_path, fmt):
    from io import StringIO

    from kulshan.cli import _emit_output
    from kulshan.coverage import build_coverage_from_results

    results = {"security": _merge_pack_results([pack(), pack(errors=["AccessDenied"])])}
    metadata = summarize_completeness(results)
    output = tmp_path / f"report.{fmt}"
    stream = StringIO()
    _emit_output(
        fmt=fmt,
        results=results,
        overall_score=0,
        overall_grade="N/A",
        account_id="fixture",
        regions=["us-east-1"],
        duration=1,
        top_actions=[],
        all_findings=[],
        scan_metadata=metadata,
        output=str(output) if fmt != "terminal" else None,
        show_pii=True,
        console=Console(file=stream),
        history_db_path=tmp_path / "history.db",
        coverage=build_coverage_from_results(results, ["us-east-1"], 1).to_dict(),
    )
    text = output.read_text(encoding="utf-8") if fmt != "terminal" else stream.getvalue()
    if fmt == "json":
        data = json.loads(text)
        assert data["overall_score"] is None
        assert data["coverage"]["summary"]["report_status"] == "partial"
    else:
        assert "Unavailable" in text
        assert "100/100" not in text


def complete_score_inputs():
    return (
        {
            "ri_sp_coverage": {"score": 20},
            "ri_sp_utilization": {"score": 22},
            "waste_detection": {"score": 18},
        },
        {"committed_pct": 70, "on_demand_pct": 30},
        {"velocity_pct": 0.1, "trend": "stable", "warning": False},
        {"hhi": 1000, "classification": "diversified"},
    )


@pytest.mark.parametrize("mode", ["empty", "partial", "missing", "unavailable", "valid"])
def test_executive_scoring_eligibility(mode):
    args = list(complete_score_inputs())
    if mode == "empty":
        args = [{}, {}, {}, {}]
    elif mode == "partial":
        args[0] = {"ri_sp_coverage": {"score": 20}}
    elif mode == "missing":
        args[2].pop("velocity_pct")
    elif mode == "unavailable":
        args[3]["status"] = "unavailable"
    result = compute_executive_scorecard(*args, total_spend=100, total_findings=0)
    if mode == "valid":
        assert isinstance(result["composite_score"], int)
        assert result["status"] == "assessed"
    else:
        assert result["composite_score"] is None
        assert result["composite_grade"] == "N/A"
        assert result["pillars"] == []
        assert result["status"] == "unavailable"
