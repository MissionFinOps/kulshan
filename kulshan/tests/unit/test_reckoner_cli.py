"""Behavioral coverage for public Reckoner Click commands."""

from __future__ import annotations

import json
from pathlib import Path

import duckdb
import pytest
from click.testing import CliRunner

from kulshan.cli import main


@pytest.fixture
def parquet(tmp_path: Path) -> Path:
    path = tmp_path / "cur.parquet"
    connection = duckdb.connect()
    connection.execute("""CREATE TABLE source AS SELECT * FROM (VALUES
        (TIMESTAMP '2026-01-05', TIMESTAMP '2026-01-06', 'Usage', 'USD', 10.0,
         'Amazon EC2', NULL, NULL),
        (TIMESTAMP '2026-01-10', TIMESTAMP '2026-01-11', 'SavingsPlanRecurringFee',
         'USD', 7.0, 'Amazon EC2', 'sp-1', 10.0),
        (TIMESTAMP '2026-01-15', TIMESTAMP '2026-01-16', 'Usage', 'USD', 3.0,
         'Amazon S3', NULL, NULL)) AS v(
         line_item_usage_start_date, line_item_usage_end_date,
         line_item_line_item_type, line_item_currency_code,
         line_item_unblended_cost, product_product_name,
         savings_plan_savings_plan_a_r_n, savings_plan_total_commitment_to_date)""")
    connection.execute("COPY source TO ? (FORMAT PARQUET)", [str(path)])
    connection.close()
    return path


def invoke(*arguments):
    return CliRunner().invoke(main, list(arguments))


def query_args(path):
    return (
        "--metric",
        "unblended-cost",
        "--period",
        "custom",
        "--start",
        "2026-01-01",
        "--end",
        "2026-02-01",
        "--path",
        str(path),
    )


def test_query_run_json_and_explain(parquet):
    result = invoke(
        "query", "run", *query_args(parquet), "--grouping", "service", "--output", "json"
    )
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["query"]["metric"] == "unblended-cost"
    assert payload["rows_returned"] == 2

    explained = invoke("query", "run", *query_args(parquet), "--explain")
    assert explained.exit_code == 0, explained.output
    assert "generated_sql" in explained.output and "SELECT" in explained.output


def test_query_terminal_output_contains_table_formatting(parquet):
    """Terminal mode produces formatted output with metric and total."""
    result = invoke(
        "query",
        "run",
        *query_args(parquet),
        "--grouping",
        "service",
        "--output",
        "terminal",
    )
    assert result.exit_code == 0
    assert "unblended-cost" in result.output
    assert "Total" in result.output or "total" in result.output


def test_query_error_and_saved_query_round_trip(tmp_path, parquet):
    bad = invoke(
        "query",
        "run",
        "--metric",
        "not-a-metric",
        "--period",
        "last-30-days",
        "--path",
        str(parquet),
        "--output",
        "json",
    )
    assert bad.exit_code != 0
    assert "metric" in bad.output.lower()

    directory = tmp_path / "queries"
    saved = invoke(
        "query",
        "save",
        "--name",
        "monthly",
        "--dir",
        str(directory),
        "--metric",
        "unblended-cost",
        "--period",
        "last-30-days",
    )
    assert saved.exit_code == 0, saved.output
    filename = directory / "monthly.json"
    assert invoke("query", "list", "--dir", str(directory)).output.strip() == "monthly"
    assert invoke("query", "validate", "--file", str(filename)).output.strip() == "valid"
    inspected = invoke("query", "inspect", "--file", str(filename))
    assert json.loads(inspected.output)["metric"] == "unblended-cost"


def test_explore_and_investigate(parquet):
    listing = invoke("explore", "--list")
    assert listing.exit_code == 0 and "where-spending" in listing.output
    explored = invoke(
        "explore", "--module", "where-spending", "--path", str(parquet), "--output", "json"
    )
    assert explored.exit_code == 0, explored.output
    assert json.loads(explored.output)["rows"]

    listing = invoke("investigate", "--list")
    assert listing.exit_code == 0 and "compute-cost" in listing.output
    investigated = invoke(
        "investigate", "--module", "compute-cost", "--path", str(parquet), "--output", "json"
    )
    assert investigated.exit_code == 0, investigated.output
    assert json.loads(investigated.output)["query"]["metric"] == "unblended-cost"


def test_session_lifecycle(tmp_path, parquet):
    directory = tmp_path / "sessions"
    common = ("--id", "case-1", "--dir", str(directory))
    assert invoke("session", "start", *common).exit_code == 0
    added = invoke("session", "add-query", *common, *query_args(parquet))
    assert added.exit_code == 0, added.output
    assert invoke("session", "add-note", *common, "--note", "reviewed").exit_code == 0
    shown = invoke("session", "show", *common)
    assert json.loads(shown.output)["entries"][0]["note"] == "reviewed"
    exported = invoke("session", "export", *common, "--output", "markdown")
    assert "# Investigation session: case-1" in exported.output
    assert invoke("session", "close", *common).exit_code == 0
    rejected = invoke("session", "add-query", *common, *query_args(parquet))
    assert rejected.exit_code != 0 and "closed" in rejected.output


def test_commitment_analysis(parquet):
    result = invoke("commitment", "analyze", "--path", str(parquet), "--output", "json")
    assert result.exit_code == 0, result.output
    profiles = json.loads(result.output)["profiles"]
    assert profiles
    assert {"commitment_type", "claim_class"} <= profiles[0].keys()
