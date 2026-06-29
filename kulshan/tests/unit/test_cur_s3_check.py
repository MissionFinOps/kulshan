from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from botocore.exceptions import ClientError
from click.testing import CliRunner

from kulshan.cli import main
from kulshan.cur.s3_check import S3CheckError, check_s3_cur_layout, parse_s3_uri


def _client_error(code: str) -> ClientError:
    return ClientError({"Error": {"Code": code, "Message": code}}, "S3Operation")


def _mock_s3_client(objects: list[dict], head_sizes: dict[str, int] | None = None) -> MagicMock:
    client = MagicMock()
    client.list_objects_v2.return_value = {"Contents": objects}
    head_sizes = head_sizes or {}

    def head_object(**kwargs) -> dict:
        return {"ContentLength": head_sizes.get(kwargs["Key"], 123)}

    client.head_object.side_effect = head_object
    return client


def test_parse_s3_uri_accepts_valid_path() -> None:
    assert parse_s3_uri("s3://billing-bucket/export/prefix/") == (
        "billing-bucket",
        "export/prefix/",
    )


def test_parse_s3_uri_rejects_non_s3_path() -> None:
    with pytest.raises(S3CheckError, match="s3://bucket/prefix") as exc:
        parse_s3_uri("./cur/")

    assert exc.value.kind == "invalid_s3_uri"


def test_s3_check_list_denied_maps_to_list_bucket() -> None:
    client = MagicMock()
    client.list_objects_v2.side_effect = _client_error("AccessDenied")

    with pytest.raises(S3CheckError) as exc:
        check_s3_cur_layout("s3://billing-bucket/export/", s3_client=client)

    assert exc.value.kind == "list_access_denied"
    assert exc.value.bucket == "billing-bucket"
    assert exc.value.prefix == "export/"
    client.head_object.assert_not_called()


def test_s3_check_parquet_head_denied_marks_probe_unreadable() -> None:
    manifest_key = "export/metadata/Manifest.json"
    parquet_key = "export/data/BILLING_PERIOD=2026-06/part-000.parquet"
    client = _mock_s3_client(
        [
            {"Key": manifest_key, "Size": 10},
            {"Key": parquet_key, "Size": 20},
        ],
        {manifest_key: 10},
    )

    def head_object(**kwargs) -> dict:
        if kwargs["Key"] == parquet_key:
            raise _client_error("403")
        return {"ContentLength": 10}

    client.head_object.side_effect = head_object

    report = check_s3_cur_layout("s3://billing-bucket/export/", s3_client=client)

    assert report.parquet.readable is False
    assert report.parquet.operation == "HeadObject"
    assert report.parquet.likely_missing_action == "s3:GetObject"
    assert report.parquet.object_arn == "arn:aws:s3:::billing-bucket/export/*"
    assert "kms:Decrypt" in report.parquet.kms_hint



def test_s3_check_manifest_head_403_marks_probe_unreadable() -> None:
    manifest_key = "export/metadata/Manifest.json"
    parquet_key = "export/data/BILLING_PERIOD=2026-06/part-000.parquet"
    client = _mock_s3_client(
        [
            {"Key": manifest_key, "Size": 10},
            {"Key": parquet_key, "Size": 20},
        ],
        {parquet_key: 20},
    )

    def head_object(**kwargs) -> dict:
        if kwargs["Key"] == manifest_key:
            raise _client_error("403")
        return {"ContentLength": 20}

    client.head_object.side_effect = head_object

    report = check_s3_cur_layout("s3://billing-bucket/export/", s3_client=client)

    assert report.manifest.readable is False
    assert report.manifest.operation == "HeadObject"
    assert report.manifest.likely_missing_action == "s3:GetObject"
    assert report.manifest.object_arn == "arn:aws:s3:::billing-bucket/export/*"
    assert "kms:Decrypt" in report.manifest.kms_hint

def test_s3_check_reports_manifest_found_and_readable() -> None:
    manifest_key = "export/metadata/Manifest.json"
    parquet_key = "export/data/BILLING_PERIOD=2026-06/part-000.parquet"
    client = _mock_s3_client(
        [
            {"Key": manifest_key, "Size": 10},
            {"Key": parquet_key, "Size": 20},
        ],
        {manifest_key: 100, parquet_key: 200},
    )

    report = check_s3_cur_layout("s3://billing-bucket/export/", s3_client=client)

    assert report.manifest_found is True
    assert report.manifest.readable is True
    assert report.manifest.size == 100
    assert report.manifest.key == manifest_key


def test_s3_check_reports_parquet_found_and_readable() -> None:
    manifest_key = "export/metadata/Manifest.json"
    parquet_key = "export/data/BILLING_PERIOD=2026-06/part-000.parquet"
    client = _mock_s3_client(
        [
            {"Key": manifest_key, "Size": 10},
            {"Key": parquet_key, "Size": 20},
        ],
        {manifest_key: 100, parquet_key: 200},
    )

    report = check_s3_cur_layout("s3://billing-bucket/export/", s3_client=client)

    assert report.parquet_found is True
    assert report.parquet.readable is True
    assert report.parquet.size == 200
    assert report.parquet.key == parquet_key


def test_s3_check_detects_billing_periods() -> None:
    client = _mock_s3_client(
        [
            {"Key": "export/metadata/Manifest.json", "Size": 10},
            {"Key": "export/data/BILLING_PERIOD=2026-05/part-000.parquet", "Size": 20},
            {"Key": "export/data/BILLING_PERIOD=2026-06/part-000.parquet", "Size": 30},
        ]
    )

    report = check_s3_cur_layout("s3://billing-bucket/export/", s3_client=client)

    assert report.billing_periods == ("2026-05", "2026-06")


def test_s3_check_reports_no_manifest_found() -> None:
    client = _mock_s3_client(
        [{"Key": "export/data/BILLING_PERIOD=2026-06/part-000.parquet", "Size": 20}]
    )

    report = check_s3_cur_layout("s3://billing-bucket/export/", s3_client=client)

    assert report.manifest_found is False
    assert report.manifest.readable is False
    assert report.parquet_found is True


def test_s3_check_reports_no_parquet_found() -> None:
    client = _mock_s3_client([{"Key": "export/metadata/Manifest.json", "Size": 10}])

    report = check_s3_cur_layout("s3://billing-bucket/export/", s3_client=client)

    assert report.parquet_found is False
    assert report.parquet.readable is False
    assert report.manifest_found is True


def test_s3_check_does_not_download_data() -> None:
    manifest_key = "export/metadata/Manifest.json"
    parquet_key = "export/data/BILLING_PERIOD=2026-06/part-000.parquet"
    client = _mock_s3_client(
        [
            {"Key": manifest_key, "Size": 10},
            {"Key": parquet_key, "Size": 20},
        ]
    )

    check_s3_cur_layout("s3://billing-bucket/export/", s3_client=client)

    client.list_objects_v2.assert_called_once_with(
        Bucket="billing-bucket",
        Prefix="export/",
        MaxKeys=50,
    )
    assert client.head_object.call_count == 2
    client.get_object.assert_not_called()


def test_cur_s3_check_cli_outputs_readiness_report(monkeypatch: pytest.MonkeyPatch) -> None:
    manifest_key = "export/metadata/Manifest.json"
    parquet_key = "export/data/BILLING_PERIOD=2026-06/part-000.parquet"
    client = _mock_s3_client(
        [
            {"Key": manifest_key, "Size": 10},
            {"Key": parquet_key, "Size": 20},
        ],
        {manifest_key: 100, parquet_key: 200},
    )
    monkeypatch.setattr("kulshan.cur.s3_check.boto3.client", lambda service: client)

    result = CliRunner().invoke(main, ["cur", "s3-check", "--s3", "s3://billing-bucket/export/"])

    assert result.exit_code == 0
    assert "S3 CUR/Data Export Readiness" in result.output
    assert "Manifest found" in result.output
    assert "Parquet found" in result.output
    assert "2026-06" in result.output
    assert (
        "aws s3 cp s3://billing-bucket/export/data/"
        "BILLING_PERIOD=2026-06/part-000.parquet"
        in result.output
    )


def test_cur_s3_check_cli_reports_list_denied(monkeypatch: pytest.MonkeyPatch) -> None:
    client = MagicMock()
    client.list_objects_v2.side_effect = _client_error("AccessDenied")
    monkeypatch.setattr("kulshan.cur.s3_check.boto3.client", lambda service: client)

    result = CliRunner().invoke(main, ["cur", "s3-check", "--s3", "s3://billing-bucket/export/"])

    assert result.exit_code != 0
    assert "s3:ListBucket" in result.output
    assert "arn:aws:s3:::billing-bucket" in result.output


def test_cur_s3_check_cli_reports_parquet_head_403_without_traceback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manifest_key = "export/metadata/Manifest.json"
    parquet_key = "export/data/BILLING_PERIOD=2026-06/part-000.parquet"
    client = _mock_s3_client(
        [
            {"Key": manifest_key, "Size": 10},
            {"Key": parquet_key, "Size": 20},
        ],
        {manifest_key: 100},
    )

    def head_object(**kwargs) -> dict:
        if kwargs["Key"] == parquet_key:
            raise _client_error("403")
        return {"ContentLength": 100}

    client.head_object.side_effect = head_object
    monkeypatch.setattr("kulshan.cur.s3_check.boto3.client", lambda service: client)

    result = CliRunner().invoke(main, ["cur", "s3-check", "--s3", "s3://billing-bucket/export/"])

    assert result.exit_code != 0
    assert "Traceback" not in result.output
    assert "S3 CUR/Data Export Readiness" in result.output
    assert "HeadObject" in result.output
    assert "s3:GetObject" in result.output
    assert "arn:aws:s3:::billing-bucket/export/*" in result.output
    assert "kms:Decrypt" in result.output


def test_cur_s3_check_cli_fails_when_manifest_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _mock_s3_client(
        [{"Key": "export/data/BILLING_PERIOD=2026-06/part-000.parquet", "Size": 20}]
    )
    monkeypatch.setattr("kulshan.cur.s3_check.boto3.client", lambda service: client)

    result = CliRunner().invoke(main, ["cur", "s3-check", "--s3", "s3://billing-bucket/export/"])

    assert result.exit_code != 0
    assert "No Manifest.json found" in result.output


def test_cur_s3_check_cli_fails_when_parquet_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _mock_s3_client([{"Key": "export/metadata/Manifest.json", "Size": 10}])
    monkeypatch.setattr("kulshan.cur.s3_check.boto3.client", lambda service: client)

    result = CliRunner().invoke(main, ["cur", "s3-check", "--s3", "s3://billing-bucket/export/"])

    assert result.exit_code != 0
    assert "No .parquet file found" in result.output

def test_cur_s3_check_cli_reports_manifest_head_403_without_traceback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manifest_key = "export/metadata/Manifest.json"
    parquet_key = "export/data/BILLING_PERIOD=2026-06/part-000.parquet"
    client = _mock_s3_client(
        [
            {"Key": manifest_key, "Size": 10},
            {"Key": parquet_key, "Size": 20},
        ],
        {parquet_key: 200},
    )

    def head_object(**kwargs) -> dict:
        if kwargs["Key"] == manifest_key:
            raise _client_error("403")
        return {"ContentLength": 200}

    client.head_object.side_effect = head_object
    monkeypatch.setattr("kulshan.cur.s3_check.boto3.client", lambda service: client)

    result = CliRunner().invoke(main, ["cur", "s3-check", "--s3", "s3://billing-bucket/export/"])

    assert result.exit_code != 0
    assert "Traceback" not in result.output
    assert "S3 CUR/Data Export Readiness" in result.output
    assert "HeadObject" in result.output
    assert "s3:GetObject" in result.output
    assert "arn:aws:s3:::billing-bucket/export/*" in result.output
    assert "kms:Decrypt" in result.output
