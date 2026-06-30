# ruff: noqa: E501
from __future__ import annotations

import shutil
from pathlib import Path

from click.testing import CliRunner

from kulshan.cli import main


def _workspace_tmp(name: str) -> Path:
    root = Path(".kulshan-test-tmp") / name
    if root.exists():
        shutil.rmtree(root)
    root.mkdir(parents=True)
    return root


def _write_non_ec2_cur(path: Path) -> Path:
    import duckdb

    cur = path / "cur"
    cur.mkdir()
    parquet = cur / "data.parquet"
    duckdb.connect(database=":memory:").execute(
        f"""
        COPY (
            SELECT * FROM (VALUES
                (TIMESTAMP '2026-06-01', 'AmazonS3', 'TimedStorage-ByteHrs', '111111111111', 'us-east-1', NULL, 1.25),
                (TIMESTAMP '2026-06-02', 'awskms', 'KMS-Requests', '111111111111', 'us-east-1', NULL, 2.50),
                (TIMESTAMP '2026-06-03', 'AWSDataTransfer', 'DataTransfer-Out-Bytes', '222222222222', 'us-west-2', NULL, 3.75)
            ) AS t(
                line_item_usage_start_date,
                line_item_product_code,
                line_item_usage_type,
                line_item_usage_account_id,
                product_region,
                line_item_net_unblended_cost,
                line_item_unblended_cost
            )
        ) TO '{parquet.as_posix()}' (FORMAT PARQUET)
        """
    )
    return cur


def test_generic_validate_passes_with_no_ec2_rows() -> None:
    cur = _write_non_ec2_cur(_workspace_tmp("generic"))

    result = CliRunner().invoke(main, ["cur", "validate", "--path", str(cur)])

    assert result.exit_code == 0
    assert "CUR validation passed" in result.output
    assert "EC2 rows" in result.output
    assert "no" in result.output


def test_validate_real_shaped_fixture_with_null_net_cost_reports_fallback() -> None:
    cur = _write_non_ec2_cur(_workspace_tmp("fallback"))

    result = CliRunner().invoke(main, ["cur", "validate", "--path", str(cur)])

    assert result.exit_code == 0
    assert "line_item_unblended_cost" in result.output
    assert "line_item_net_unblended_cost was null" in result.output


def test_validate_reports_top_product_codes_and_usage_types() -> None:
    cur = _write_non_ec2_cur(_workspace_tmp("top-counts"))

    result = CliRunner().invoke(main, ["cur", "validate", "--path", str(cur)])

    assert result.exit_code == 0
    assert "Top Product Codes" in result.output
    assert "AmazonS3" in result.output
    assert "Top Usage Types" in result.output
    assert "TimedStorage-ByteHrs" in result.output


def test_investigate_ec2_still_exits_nonzero_with_no_ec2_rows() -> None:
    cur = _write_non_ec2_cur(_workspace_tmp("ec2"))

    result = CliRunner().invoke(
        main, ["investigate", "ec2", "--cur", str(cur), "--month", "2026-06"]
    )

    assert result.exit_code != 0
    assert "No EC2 cost data" in result.output or "Need at least" in result.output
