# ruff: noqa: E501
from __future__ import annotations

import json
from io import BytesIO
from unittest.mock import MagicMock

import pytest
from botocore.exceptions import ClientError

from kulshan.cur.manifest_reader import CurManifestError, read_manifest


def _client_error(code: str) -> ClientError:
    return ClientError({"Error": {"Code": code, "Message": code}}, "S3")


def _client(
    manifest: dict, *, list_key: str = "export/metadata/BILLING_PERIOD=2026-06/aManifest.json"
):
    client = MagicMock()
    client.list_objects_v2.return_value = {"Contents": [{"Key": list_key, "Size": 321}]}
    client.get_object.return_value = {"Body": BytesIO(json.dumps(manifest).encode("utf-8"))}
    client.head_object.return_value = {"ContentLength": 70}
    return client


def test_manifest_found_and_parsed() -> None:
    client = _client(
        {
            "exportName": "cur-export",
            "columns": [{"name": "line_item_unblended_cost"}],
            "dataFileS3Keys": [
                {"s3Key": "export/data/BILLING_PERIOD=2026-06/part.parquet", "sizeBytes": 70}
            ],
        }
    )

    manifest = read_manifest("bucket", "export/", "2026-06", s3_client=client)

    assert manifest.export_name == "cur-export"
    assert manifest.manifest_key.endswith("Manifest.json")
    assert manifest.manifest_size_bytes == 321
    assert manifest.files[0].s3_key.endswith("part.parquet")
    assert manifest.columns == ("line_item_unblended_cost",)


def test_manifest_not_found_gives_useful_error() -> None:
    client = MagicMock()
    client.list_objects_v2.return_value = {"Contents": []}

    with pytest.raises(CurManifestError, match="kulshan cur s3-check"):
        read_manifest("bucket", "export/", "2026-06", s3_client=client)


def test_manifest_get_access_denied_gives_iam_hint() -> None:
    client = MagicMock()
    client.list_objects_v2.return_value = {
        "Contents": [{"Key": "export/metadata/BILLING_PERIOD=2026-06/Manifest.json", "Size": 1}]
    }
    client.get_object.side_effect = _client_error("AccessDenied")

    with pytest.raises(CurManifestError, match="s3:GetObject"):
        read_manifest("bucket", "export/", "2026-06", s3_client=client)


def test_manifest_malformed_json_includes_manifest_key() -> None:
    client = MagicMock()
    key = "export/metadata/BILLING_PERIOD=2026-06/Manifest.json"
    client.list_objects_v2.return_value = {"Contents": [{"Key": key, "Size": 1}]}
    client.get_object.return_value = {"Body": BytesIO(b"not-json")}

    with pytest.raises(CurManifestError, match=key):
        read_manifest("bucket", "export/", "2026-06", s3_client=client)


def test_manifest_fallback_discovery_under_metadata() -> None:
    client = MagicMock()
    client.list_objects_v2.side_effect = [
        {"Contents": []},
        {"Contents": [{"Key": "export/metadata/Manifest.json", "Size": 10}]},
    ]
    client.get_object.return_value = {
        "Body": BytesIO(
            json.dumps({"dataFileS3Keys": ["export/data/BILLING_PERIOD=2026-06/a.parquet"]}).encode(
                "utf-8"
            )
        )
    }

    manifest = read_manifest("bucket", "export/", "2026-06", s3_client=client)

    assert manifest.manifest_key == "export/metadata/Manifest.json"


def test_manifest_total_size_sums_correctly() -> None:
    client = _client(
        {
            "dataFileS3Keys": [
                {"s3Key": "export/data/a.parquet", "sizeBytes": 10},
                {"s3Key": "export/data/b.parquet", "sizeBytes": 20},
            ]
        }
    )

    manifest = read_manifest("bucket", "export/", "2026-06", s3_client=client)

    assert manifest.total_size_bytes == 30


def test_manifest_s3_glob_builds_correctly() -> None:
    client = _client(
        {
            "dataFileS3Keys": [
                {"s3Key": "export/data/a.parquet", "sizeBytes": 10},
                {"s3Key": "export/data/b.parquet", "sizeBytes": 20},
            ]
        }
    )

    manifest = read_manifest("bucket", "export/", "2026-06", s3_client=client)

    assert manifest.s3_glob == "s3://bucket/export/data/*.parquet"
