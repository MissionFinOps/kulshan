"""Workspace-local manifest-versioned CUR catalogue.

The catalogue is metadata-only: it never downloads billing data or materializes
DuckDB cache tables. Every refresh writes a new manifest version atomically and
retains prior versions for auditability.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

CATALOG_SCHEMA_VERSION = 1


@dataclass(frozen=True)
class CatalogExport:
    export_id: str
    provider: str
    export_name: str
    export_arn: str
    bucket: str
    prefix: str
    region: str
    format: str
    table_name: str | None
    status: str
    payer_account_id: str | None
    authority_scope: str
    schema_era: str | None = None


@dataclass(frozen=True)
class CatalogManifest:
    manifest_id: str
    export_id: str
    created_at: str
    file_count: int
    total_bytes: int
    schema_fingerprint: str | None
    periods: tuple[str, ...]
    refresh_state: str


@dataclass(frozen=True)
class CatalogStatus:
    schema_version: int
    export_count: int
    manifest_count: int
    latest_manifest: str | None
    coverage_start: str | None
    coverage_end: str | None
    delivery_state: str
    access_state: str
    schema_state: str
    payer_state: str
    settlement_state: str
    cache_state: str


class CatalogError(RuntimeError):
    """Base catalogue error."""


class CatalogValidationError(CatalogError):
    """Invalid catalogue input."""


def catalog_path(workspace_path: Path) -> Path:
    return workspace_path / "cur-catalog.db"


def _connect(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def initialize_catalog(workspace_path: Path) -> Path:
    path = catalog_path(workspace_path)
    with _connect(path) as db:
        db.executescript(
            """
            CREATE TABLE IF NOT EXISTS catalog_meta (
              key TEXT PRIMARY KEY, value TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS exports (
              export_id TEXT PRIMARY KEY, provider TEXT NOT NULL,
              export_name TEXT NOT NULL, export_arn TEXT NOT NULL DEFAULT '',
              bucket TEXT NOT NULL, prefix TEXT NOT NULL DEFAULT '',
              region TEXT NOT NULL, format TEXT NOT NULL,
              table_name TEXT, status TEXT NOT NULL,
              payer_account_id TEXT, authority_scope TEXT NOT NULL,
              schema_era TEXT, first_seen_at TEXT NOT NULL,
              UNIQUE(provider, export_name, bucket, prefix)
            );
            CREATE TABLE IF NOT EXISTS manifests (
              manifest_id TEXT PRIMARY KEY, export_id TEXT NOT NULL,
              created_at TEXT NOT NULL, file_count INTEGER NOT NULL,
              total_bytes INTEGER NOT NULL, schema_fingerprint TEXT,
              periods_json TEXT NOT NULL, refresh_state TEXT NOT NULL,
              FOREIGN KEY(export_id) REFERENCES exports(export_id)
            );
            CREATE TABLE IF NOT EXISTS manifest_files (
              manifest_id TEXT NOT NULL, object_key TEXT NOT NULL,
              etag TEXT, version_id TEXT, size_bytes INTEGER,
              last_modified TEXT, schema_fingerprint TEXT,
              PRIMARY KEY(manifest_id, object_key),
              FOREIGN KEY(manifest_id) REFERENCES manifests(manifest_id)
            );
            CREATE TABLE IF NOT EXISTS field_availability (
              manifest_id TEXT NOT NULL, field_name TEXT NOT NULL,
              schema_era TEXT, nullable INTEGER NOT NULL,
              PRIMARY KEY(manifest_id, field_name),
              FOREIGN KEY(manifest_id) REFERENCES manifests(manifest_id)
            );
            CREATE TABLE IF NOT EXISTS state (
              key TEXT PRIMARY KEY, value TEXT NOT NULL, reason TEXT
            );
            INSERT OR IGNORE INTO catalog_meta(key, value)
              VALUES ('schema_version', '1');
            INSERT OR IGNORE INTO state(key, value, reason) VALUES
              ('delivery', 'unknown', 'No catalogue refresh has run'),
              ('access', 'unknown', 'No catalogue access check has run'),
              ('schema', 'unknown', 'No manifest schema has been verified'),
              ('payer', 'unknown', 'No payer evidence has been recorded'),
              ('settlement', 'unknown', 'Invoice settlement is not inferred from CUR'),
              ('cache', 'not-built', 'PR 2 does not materialize cache data');
            """
        )
    return path


def _stable_id(*parts: str) -> str:
    return hashlib.sha256("\x1f".join(parts).encode()).hexdigest()[:32]


def record_export(workspace_path: Path, export: CatalogExport) -> str:
    initialize_catalog(workspace_path)
    if not export.bucket or not export.export_name:
        raise CatalogValidationError("export name and bucket are required")
    export_id = export.export_id or _stable_id(
        export.provider, export.export_name, export.bucket, export.prefix
    )
    now = datetime.now(timezone.utc).isoformat()
    with _connect(catalog_path(workspace_path)) as db:
        db.execute(
            """INSERT INTO exports(export_id,provider,export_name,export_arn,bucket,
            prefix,region,format,table_name,status,payer_account_id,authority_scope,
            schema_era,first_seen_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(export_id) DO UPDATE SET status=excluded.status,
            format=excluded.format, table_name=excluded.table_name,
            payer_account_id=excluded.payer_account_id,
            authority_scope=excluded.authority_scope, schema_era=excluded.schema_era""",
            (
                export_id,
                export.provider,
                export.export_name,
                export.export_arn,
                export.bucket,
                export.prefix,
                export.region,
                export.format,
                export.table_name,
                export.status,
                export.payer_account_id,
                export.authority_scope,
                export.schema_era,
                now,
            ),
        )
    return export_id


def record_manifest(
    workspace_path: Path,
    export_id: str,
    *,
    files: Iterable[Mapping[str, Any]],
    periods: Iterable[str] = (),
    schema_fingerprint: str | None = None,
    refresh_state: str = "complete",
) -> CatalogManifest:
    initialize_catalog(workspace_path)
    rows = list(files)
    if not db_export_exists(workspace_path, export_id):
        raise CatalogValidationError(f"unknown export_id: {export_id}")
    normalized = sorted(rows, key=lambda row: str(row.get("object_key", "")))
    if any(not row.get("object_key") for row in normalized):
        raise CatalogValidationError("manifest files require object_key")
    manifest_id = _stable_id(
        export_id, json.dumps(normalized, sort_keys=True), json.dumps(sorted(set(periods)))
    )
    created = datetime.now(timezone.utc).isoformat()
    total = sum(int(row.get("size_bytes") or 0) for row in normalized)
    period_tuple = tuple(sorted({str(period) for period in periods}))
    with _connect(catalog_path(workspace_path)) as db:
        db.execute(
            "INSERT OR REPLACE INTO manifests VALUES(?,?,?,?,?,?,?,?)",
            (
                manifest_id,
                export_id,
                created,
                len(normalized),
                total,
                schema_fingerprint,
                json.dumps(period_tuple),
                refresh_state,
            ),
        )
        db.execute("DELETE FROM manifest_files WHERE manifest_id=?", (manifest_id,))
        for row in normalized:
            db.execute(
                "INSERT INTO manifest_files VALUES(?,?,?,?,?,?,?)",
                (
                    manifest_id,
                    str(row["object_key"]),
                    row.get("etag"),
                    row.get("version_id"),
                    row.get("size_bytes"),
                    row.get("last_modified"),
                    row.get("schema_fingerprint"),
                ),
            )
        db.execute(
            "UPDATE state SET value='known', reason='Manifest recorded' WHERE key='delivery'"
        )
    return CatalogManifest(
        manifest_id,
        export_id,
        created,
        len(normalized),
        total,
        schema_fingerprint,
        period_tuple,
        refresh_state,
    )


def db_export_exists(workspace_path: Path, export_id: str) -> bool:
    with _connect(catalog_path(workspace_path)) as db:
        return (
            db.execute("SELECT 1 FROM exports WHERE export_id=?", (export_id,)).fetchone()
            is not None
        )


def status(workspace_path: Path) -> CatalogStatus:
    initialize_catalog(workspace_path)
    with _connect(catalog_path(workspace_path)) as db:
        exports = db.execute("SELECT count(*) FROM exports").fetchone()[0]
        manifests = db.execute("SELECT count(*) FROM manifests").fetchone()[0]
        latest = db.execute(
            "SELECT manifest_id FROM manifests ORDER BY created_at DESC LIMIT 1"
        ).fetchone()
        periods = db.execute("SELECT periods_json FROM manifests").fetchall()
        all_periods = sorted({p for row in periods for p in json.loads(row[0])})
        states = {row[0]: row[1] for row in db.execute("SELECT key,value FROM state")}
    return CatalogStatus(
        1,
        exports,
        manifests,
        latest[0] if latest else None,
        all_periods[0] if all_periods else None,
        all_periods[-1] if all_periods else None,
        *(
            states.get(key, "unknown")
            for key in ("delivery", "access", "schema", "payer", "settlement", "cache")
        ),
    )


def list_manifests(workspace_path: Path) -> tuple[CatalogManifest, ...]:
    initialize_catalog(workspace_path)
    with _connect(catalog_path(workspace_path)) as db:
        rows = db.execute("SELECT * FROM manifests ORDER BY created_at DESC").fetchall()
    return tuple(
        CatalogManifest(
            row["manifest_id"],
            row["export_id"],
            row["created_at"],
            row["file_count"],
            row["total_bytes"],
            row["schema_fingerprint"],
            tuple(json.loads(row["periods_json"])),
            row["refresh_state"],
        )
        for row in rows
    )


def doctor(workspace_path: Path) -> tuple[str, ...]:
    """Return actionable catalogue consistency findings without touching data."""
    initialize_catalog(workspace_path)
    findings: list[str] = []
    with _connect(catalog_path(workspace_path)) as db:
        orphan = db.execute(
            "SELECT count(*) FROM manifests m LEFT JOIN exports e "
            "ON e.export_id=m.export_id WHERE e.export_id IS NULL"
        ).fetchone()[0]
        bad = db.execute(
            "SELECT count(*) FROM manifests WHERE file_count < 0 OR total_bytes < 0"
        ).fetchone()[0]
    if orphan:
        findings.append(f"{orphan} manifests reference missing exports")
    if bad:
        findings.append(f"{bad} manifests have negative size or file count")
    return tuple(findings)


@dataclass(frozen=True)
class StorageEstimate:
    manifest_count: int
    known_bytes: int
    known_files: int
    s3_estimate_required: bool
    cache_consent_required: bool


def storage_estimate(workspace_path: Path) -> StorageEstimate:
    """Return known metadata sizes without scanning or downloading S3 objects."""
    initialize_catalog(workspace_path)
    with _connect(catalog_path(workspace_path)) as db:
        row = db.execute(

                "SELECT count(*), coalesce(sum(total_bytes), 0), "
                "coalesce(sum(file_count), 0) FROM manifests"

        ).fetchone()
    count, total, files = (int(row[0]), int(row[1]), int(row[2]))
    return StorageEstimate(count, total, files, count == 0, False)


def record_discovered_exports(workspace_path: Path, exports: Iterable[Any]) -> int:
    """Persist read-only discovery metadata and return the number recorded."""
    count = 0
    for export in exports:
        record_export(
            workspace_path,
            CatalogExport(
                export_id="",
                provider=export.provider,
                export_name=export.export_name,
                export_arn=export.export_arn,
                bucket=export.s3_bucket,
                prefix=export.s3_prefix,
                region=export.s3_region,
                format=export.format,
                table_name=export.table_name,
                status=export.status,
                payer_account_id=None,
                authority_scope=export.authority_scope,
            ),
        )
        count += 1
    return count
