"""Consultant evidence package assembly.

Creates the final ZIP containing CUR, CE, manifest, privacy report, and README.
"""
from __future__ import annotations

import json
import zipfile
from datetime import datetime, timezone
from pathlib import Path

from kulshan.__version__ import __version__
from kulshan.export.columns import ColumnClass
from kulshan.export.scope import EvidenceScope


def create_package(
    output_path: Path,
    cur_dir: Path | None,
    ce_dir: Path | None,
    scope: EvidenceScope,
    classification: dict[str, ColumnClass],
    gate_results: list[dict],
    cur_row_count: int = 0,
    ce_datasets: list[str] | None = None,
    dropped_columns: list[str] | None = None,
    keep_tags: list[str] | None = None,
) -> Path:
    """Assemble the consultant evidence ZIP package.

    Args:
        output_path: Final ZIP file path.
        cur_dir: Directory containing CUR Parquet files.
        ce_dir: Directory containing CE Parquet files.
        scope: EvidenceScope used for this export.
        classification: Column classification results.
        gate_results: List of gate result dicts.
        cur_row_count: Total CUR rows exported.
        ce_datasets: List of CE dataset names.
        dropped_columns: Columns dropped from export.
        keep_tags: Explicitly kept tag keys.

    Returns:
        Path to created ZIP.
    """
    manifest = _build_manifest(scope, classification, cur_row_count, ce_datasets, keep_tags)
    privacy_report = _build_privacy_report(
        classification, gate_results, dropped_columns, keep_tags
    )
    readme = _build_readme(scope, cur_row_count, ce_datasets, dropped_columns)

    with zipfile.ZipFile(output_path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("manifest.json", json.dumps(manifest, indent=2))
        zf.writestr("privacy-report.json", json.dumps(privacy_report, indent=2))
        zf.writestr("README.md", readme)

        if cur_dir and cur_dir.exists():
            for f in sorted(cur_dir.rglob("*.parquet")):
                arcname = f"cur/{f.relative_to(cur_dir).as_posix()}"
                zf.write(f, arcname)

        if ce_dir and ce_dir.exists():
            for f in sorted(ce_dir.rglob("*.parquet")):
                arcname = f"ce/{f.relative_to(ce_dir).as_posix()}"
                zf.write(f, arcname)

    return output_path


def _build_manifest(
    scope: EvidenceScope,
    classification: dict[str, ColumnClass],
    cur_row_count: int,
    ce_datasets: list[str] | None,
    keep_tags: list[str] | None,
) -> dict:
    counts = {}
    for cls in ColumnClass:
        counts[cls.value] = sum(1 for c in classification.values() if c == cls)

    return {
        "kulshan_version": __version__,
        "export_type": "consultant-evidence",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "pseudonymization": {
            "policy": "consultant-strict-v1",
            "engine_version": __version__,
            "alias_format": "16-hex HMAC-SHA256",
            "bypass_available": False,
        },
        "scope": scope.to_dict(),
        "cur": {
            "row_count": cur_row_count,
            "column_classification": counts,
        },
        "ce": {
            "datasets": ce_datasets or [],
        },
        "keep_tags": keep_tags or [],
    }


def _build_privacy_report(
    classification: dict[str, ColumnClass],
    gate_results: list[dict],
    dropped_columns: list[str] | None,
    keep_tags: list[str] | None,
) -> dict:
    return {
        "policy": "consultant-strict-v1",
        "column_treatment": {
            col: cls.value for col, cls in sorted(classification.items())
        },
        "dropped_columns": sorted(dropped_columns) if dropped_columns else [],
        "kept_tags": sorted(keep_tags) if keep_tags else [],
        "gates": gate_results,
        "note": (
            "This report describes what Kulshan transformed. "
            "Known direct identifier classes are pseudonymized. "
            "Costs, usage quantities, and dates are preserved exactly."
        ),
    }


def _build_readme(
    scope: EvidenceScope,
    cur_row_count: int,
    ce_datasets: list[str] | None,
    dropped_columns: list[str] | None,
) -> str:
    lines = [
        "# Kulshan Consultant Evidence Package",
        "",
        f"Created: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}",
        f"Kulshan version: {__version__}",
        "",
        "## Scope",
        "",
        f"- Period: {scope.from_date} to {scope.to_date}",
    ]
    if scope.include_accounts:
        lines.append(f"- Accounts (included): {len(scope.include_accounts)} accounts")
    if scope.exclude_accounts:
        lines.append(f"- Accounts (excluded): {len(scope.exclude_accounts)} accounts")
    if scope.include_services:
        lines.append(f"- Services (included): {', '.join(scope.include_services)}")
    if scope.exclude_services:
        lines.append(f"- Services (excluded): {', '.join(scope.exclude_services)}")

    lines.extend([
        "",
        "## Contents",
        "",
        f"- CUR rows: {cur_row_count:,}",
        f"- CE datasets: {len(ce_datasets) if ce_datasets else 0}",
    ])

    if dropped_columns:
        lines.extend([
            "",
            "## Dropped Columns",
            "",
            "The following columns were removed from the export:",
            "",
        ])
        for col in sorted(dropped_columns):
            lines.append(f"- {col}")

    lines.extend([
        "",
        "## Privacy",
        "",
        "All customer-identifying values (account IDs, resource IDs, ARNs, tag values)",
        "are replaced with deterministic HMAC-derived pseudonyms.",
        "",
        "Costs, usage quantities, service names, regions, and dates are preserved exactly.",
        "",
        "See privacy-report.json for the complete column treatment manifest.",
    ])

    return "\n".join(lines) + "\n"
