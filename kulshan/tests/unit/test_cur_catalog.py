from pathlib import Path

import pytest

from kulshan.cur.catalog import (
    CatalogExport,
    CatalogValidationError,
    doctor,
    initialize_catalog,
    list_manifests,
    record_export,
    record_manifest,
    status,
    storage_estimate,
)


def _export() -> CatalogExport:
    return CatalogExport(
        export_id="export-1",
        provider="legacy-cur",
        export_name="monthly",
        export_arn="",
        bucket="billing-bucket",
        prefix="cur/monthly",
        region="ca-central-1",
        format="Parquet",
        table_name="LEGACY_CUR",
        status="HEALTHY",
        payer_account_id="123456789012",
        authority_scope="payer-connection",
        schema_era="legacy",
    )


def test_initialize_catalog_is_workspace_local_and_idempotent(tmp_path: Path) -> None:
    path = initialize_catalog(tmp_path)
    assert path == tmp_path / "cur-catalog.db"
    assert initialize_catalog(tmp_path) == path
    assert status(tmp_path).cache_state == "not-built"
    estimate = storage_estimate(tmp_path)
    assert estimate.s3_estimate_required is True
    assert estimate.cache_consent_required is False


def test_manifest_is_deterministic_and_retains_metadata(tmp_path: Path) -> None:
    export_id = record_export(tmp_path, _export())
    files = [
        {"object_key": "b.parquet", "size_bytes": 20},
        {"object_key": "a.parquet", "size_bytes": 10},
    ]
    first = record_manifest(
        tmp_path, export_id, files=files, periods=["2026-02", "2026-01"], schema_fingerprint="abc"
    )
    second = record_manifest(
        tmp_path,
        export_id,
        files=list(reversed(files)),
        periods=["2026-01", "2026-02"],
        schema_fingerprint="abc",
    )
    assert first.manifest_id == second.manifest_id
    assert first.file_count == 2 and first.total_bytes == 30
    assert list_manifests(tmp_path)[0].periods == ("2026-01", "2026-02")
    current = status(tmp_path)
    assert (current.coverage_start, current.coverage_end) == ("2026-01", "2026-02")


def test_invalid_manifest_and_doctor_findings(tmp_path: Path) -> None:
    with pytest.raises(CatalogValidationError):
        record_manifest(tmp_path, "missing", files=[])
    record_export(tmp_path, _export())
    with pytest.raises(CatalogValidationError):
        record_manifest(tmp_path, "export-1", files=[{"size_bytes": 1}])
    assert doctor(tmp_path) == ()
