"""Deterministically deduplicate the frozen AWS CUDOS concept inventory."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Any


def _slug(value: str) -> str:
    normalized = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    if not normalized:
        raise ValueError("concept name does not produce a stable identifier")
    return normalized


def build_catalogue(raw: dict[str, Any]) -> dict[str, Any]:
    if raw.get("schema_version") != "1.0":
        raise ValueError("unsupported raw concept schema_version")
    grouped: dict[tuple[str, str], dict[str, Any]] = {}
    for item in raw.get("concepts", []):
        category = str(item["category"]).strip().lower()
        name = str(item["name"]).strip()
        key = (category, _slug(name))
        source = {
            "source_id": item["source_id"],
            "source_file": item["source_file"],
            "source_locator": item["source_locator"],
        }
        if key not in grouped:
            grouped[key] = {
                "concept_id": f"{category}:{key[1]}",
                "category": category,
                "name": name,
                "description": str(item["description"]).strip(),
                "source_references": [source],
            }
        elif source not in grouped[key]["source_references"]:
            grouped[key]["source_references"].append(source)
    concepts = []
    for key in sorted(grouped):
        concept = grouped[key]
        concept["source_references"] = sorted(
            concept["source_references"],
            key=lambda item: (
                item["source_id"],
                item["source_file"],
                item["source_locator"],
            ),
        )
        concepts.append(concept)
    canonical = json.dumps(concepts, sort_keys=True, separators=(",", ":")).encode()
    return {
        "schema_version": "1.0",
        "catalogue_id": "aws-cudos-semantics-v1",
        "content_sha256": hashlib.sha256(canonical).hexdigest(),
        "concepts": concepts,
    }


def build_report(catalogue: dict[str, Any]) -> str:
    counts: dict[str, int] = {}
    for concept in catalogue["concepts"]:
        counts[concept["category"]] = counts.get(concept["category"], 0) + 1
    lines = [
        "# AWS CUDOS semantic extraction report",
        "",
        "This deterministic inventory deduplicates upstream analytical semantics.",
        "It is not a visual backlog and does not claim formula implementation.",
        "",
        f"Catalogue: `{catalogue['catalogue_id']}`",
        f"Content SHA-256: `{catalogue['content_sha256']}`",
        f"Unique concepts: {len(catalogue['concepts'])}",
        "",
        "## Categories",
        "",
    ]
    lines.extend(f"- `{category}`: {counts[category]}" for category in sorted(counts))
    lines.extend(
        [
            "",
            "## Deduplication rule",
            "",
            "Concepts are keyed by normalized category and name. Repeated visual variants",
            "share one semantic record and accumulate stable source references. Grouped",
            "spend by service, account, region, usage type, operation, or resource is one",
            "grouped-query concept rather than separate implementation work.",
            "",
        ]
    )
    return "\n".join(lines)


def generate(raw_path: Path, catalogue_path: Path, report_path: Path) -> None:
    raw = json.loads(raw_path.read_text(encoding="utf-8"))
    catalogue = build_catalogue(raw)
    catalogue_path.write_text(
        json.dumps(catalogue, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    report_path.write_text(build_report(catalogue), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("raw", type=Path)
    parser.add_argument("catalogue", type=Path)
    parser.add_argument("report", type=Path)
    args = parser.parse_args()
    generate(args.raw, args.catalogue, args.report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
