"""Generate a traceable inventory and semantic catalogue from pinned CUDOS sources."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml
from verify_aws_cudos_upstream import load_manifest, verify_repository

VERSION = "1.0"
FIELD_REF = re.compile(r"\{([^{}]+)\}")
VIEW_RE = re.compile(r"\bcreate\s+(?:or\s+replace\s+)?view\s+([A-Za-z_]\w*)", re.I)


class ExtractionError(RuntimeError):
    """Pinned source extraction failed closed."""


class PinnedSafeLoader(yaml.SafeLoader):
    """Safe YAML loader preserving CloudFormation tags as inert values."""


def _tag(loader: PinnedSafeLoader, suffix: str, node: yaml.Node) -> dict[str, Any]:
    if isinstance(node, yaml.ScalarNode):
        value: Any = loader.construct_scalar(node)
    elif isinstance(node, yaml.SequenceNode):
        value = loader.construct_sequence(node, deep=True)
    else:
        value = loader.construct_mapping(node, deep=True)
    return {"cloudformation_tag": suffix, "value": value}


PinnedSafeLoader.add_multi_constructor("!", _tag)


@dataclass(frozen=True)
class SourceFile:
    source_id: str
    repository: str
    commit: str
    path: str
    blob: str
    local_path: Path


def canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)


def slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-") or "unnamed"


def record(source: SourceFile, path: str, category: str, name: str, raw: Any) -> dict[str, Any]:
    material = "\0".join((source.source_id, source.path, path, category, name))
    return {
        "inventory_id": "inv-" + hashlib.sha256(material.encode()).hexdigest()[:20],
        "source_repository": source.repository,
        "source_commit": source.commit,
        "source_file": source.path,
        "source_path": path,
        "source_blob_hash": source.blob,
        "raw_name": name,
        "raw_definition": raw,
        "category": category,
    }


def walk(value: Any, path: str = ""):
    if isinstance(value, dict):
        for key, child in value.items():
            child_path = f"{path}.{key}" if path else str(key)
            yield child_path, str(key), child
            yield from walk(child, child_path)
    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield from walk(child, f"{path}[{index}]")


def field_refs(value: Any) -> list[str]:
    return sorted(set(FIELD_REF.findall(canonical(value))))


def expression_category(name: str, expression: str) -> str:
    text = f"{name} {expression}".lower()
    patterns = (
        ("commitment-calculation", r"commitment|reserved|reservation|savings.?plan"),
        ("recommendation-candidate", r"recommend|potential savings|unused|rightsiz"),
        ("comparison-expression", r"previous|prior|delta|difference|growth|variance"),
        ("period-expression", r"period|billing month|usage date|dateadd|truncdate|extract\("),
        ("charge-classification", r"charge.?type|charge.?category|credit|refund|support|tax"),
        ("service-grouping", r"service.?category|service.?group"),
    )
    return next(
        (category for category, pattern in patterns if re.search(pattern, text)), "calculated-field"
    )


def parse_dashboard(source: SourceFile, doc: dict[str, Any]) -> tuple[list, list]:
    items: list[dict[str, Any]] = []
    unsupported = [
        {"source_file": source.path, "source_path": key, "reason": "unknown top-level key"}
        for key in sorted(
            set(doc)
            - {
                "AnalysisDefaults",
                "CalculatedFields",
                "ColumnConfigurations",
                "DataSetIdentifierDeclarations",
                "FilterGroups",
                "Options",
                "ParameterDeclarations",
                "Sheets",
            }
        )
    ]
    for index, value in enumerate(doc.get("CalculatedFields", [])):
        if not {"Name", "Expression", "DataSetIdentifier"} <= set(value):
            raise ExtractionError(f"malformed CalculatedFields[{index}]")
        name, expression = str(value["Name"]), str(value["Expression"])
        items.append(
            record(
                source,
                f"CalculatedFields[{index}]",
                expression_category(name, expression),
                name,
                {"dataset": value["DataSetIdentifier"], "expression": expression},
            )
        )
    for index, value in enumerate(doc.get("DataSetIdentifierDeclarations", [])):
        name = str(value.get("Identifier") or value.get("DataSetIdentifier") or f"dataset-{index}")
        items.append(
            record(source, f"DataSetIdentifierDeclarations[{index}]", "dataset", name, value)
        )
    for index, value in enumerate(doc.get("ParameterDeclarations", [])):
        if not isinstance(value, dict) or len(value) != 1:
            raise ExtractionError(f"malformed ParameterDeclarations[{index}]")
        kind, definition = next(iter(value.items()))
        name = str(definition.get("Name", f"parameter-{index}"))
        items.append(
            record(
                source,
                f"ParameterDeclarations[{index}]",
                "parameter",
                name,
                {"parameter_type": kind, "definition": definition},
            )
        )
    for index, value in enumerate(doc.get("FilterGroups", [])):
        filters = [
            {"type": next(iter(item), "UnknownFilter"), "definition": next(iter(item.values()), {})}
            for item in value.get("Filters", [])
        ]
        raw = {
            "filter_group_id": value.get("FilterGroupId"),
            "scope": value.get("ScopeConfiguration"),
            "status": value.get("Status"),
            "filters": filters,
        }
        name = str(value.get("FilterGroupId", f"filter-group-{index}"))
        items.append(record(source, f"FilterGroups[{index}]", "filter-group", name, raw))
    for sheet_index, sheet in enumerate(doc.get("Sheets", [])):
        sheet_path = f"Sheets[{sheet_index}]"
        sheet_name = str(sheet.get("Name", sheet.get("SheetId", f"sheet-{sheet_index}")))
        items.append(
            record(
                source,
                sheet_path,
                "dashboard-sheet",
                sheet_name,
                {"sheet_id": sheet.get("SheetId"), "content_type": sheet.get("ContentType")},
            )
        )
        for index, control in enumerate(sheet.get("FilterControls", [])):
            kind = next(iter(control), "UnknownControl")
            definition = control.get(kind, {})
            name = str(definition.get("FilterControlId", kind))
            items.append(
                record(
                    source, f"{sheet_path}.FilterControls[{index}]", "filter-control", name, control
                )
            )
        for index, visual in enumerate(sheet.get("Visuals", [])):
            kind = next((key for key in visual if key.endswith("Visual")), "UnknownVisual")
            definition = visual.get(kind, {})
            visual_id = str(definition.get("VisualId", f"{sheet_name}-{index}"))
            visual_path = f"{sheet_path}.Visuals[{index}]"
            items.append(
                record(
                    source,
                    visual_path,
                    "dashboard-visual",
                    visual_id,
                    {
                        "sheet": sheet_name,
                        "visual_type": kind,
                        "field_references": field_refs(definition),
                    },
                )
            )
            for drill_index, hierarchy in enumerate(definition.get("ColumnHierarchies", [])):
                hierarchy_type = next(iter(hierarchy), "UnknownHierarchy")
                hierarchy_definition = hierarchy.get(hierarchy_type, {})
                columns = hierarchy_definition.get("Columns", [])
                raw_hierarchy = {
                    "sheet": sheet_name,
                    "visual_id": visual_id,
                    "hierarchy_type": hierarchy_type,
                    "columns": columns,
                }
                column_names = [str(column.get("ColumnName", "unknown")) for column in columns]
                hierarchy_name = f"{hierarchy_type}:{'>'.join(column_names) or 'implicit'}"
                items.append(
                    record(
                        source,
                        f"{visual_path}.ColumnHierarchies[{drill_index}]",
                        "drilldown",
                        hierarchy_name,
                        raw_hierarchy,
                    )
                )
    return items, unsupported


def parse_source(source: SourceFile) -> tuple[list, list]:
    suffix = source.local_path.suffix.lower()
    text = source.local_path.read_text(encoding="utf-8")
    if suffix == ".sql":
        sql = "\n".join(line.rstrip() for line in text.strip().splitlines())
        match = VIEW_RE.search(sql)
        return [
            record(
                source,
                "$",
                "sql-view",
                match.group(1) if match else source.local_path.stem,
                {"sql": sql},
            )
        ], []
    if suffix == ".json":
        doc = json.loads(text)
        name = str(doc.get("Name", source.local_path.stem))
        raw = {
            "name": name,
            "physical_table_count": len(doc.get("PhysicalTableMap", {})),
            "logical_table_count": len(doc.get("LogicalTableMap", {})),
            "column_group_count": len(doc.get("ColumnGroups", [])),
        }
        return [record(source, "$", "dataset-definition", name, raw)], []
    if suffix in {".md", ".markdown"}:
        found = []
        for index, match in enumerate(re.finditer(r"(?ms)^```(?:sql)?\s*\n(.*?)^```", text)):
            body = match.group(1).strip()
            if re.search(r"\bselect\b.+\bfrom\b", body, re.I | re.S):
                found.append(
                    record(
                        source,
                        f"fenced-code[{index}]",
                        "documented-sql-expression",
                        f"{source.local_path.stem}-sql-{index}",
                        {"expression": body},
                    )
                )
        skipped = (
            []
            if found
            else [
                {
                    "source_file": source.path,
                    "source_path": "$",
                    "reason": "documentation context contains no fenced SQL",
                }
            ]
        )
        return found, skipped
    if suffix not in {".yaml", ".yml"}:
        return [], [
            {
                "source_file": source.path,
                "source_path": "$",
                "reason": f"unsupported file type {suffix}",
            }
        ]
    try:
        doc = yaml.load(text, Loader=PinnedSafeLoader)
    except yaml.YAMLError as exc:
        raise ExtractionError(f"malformed YAML {source.path}: {exc}") from exc
    if not isinstance(doc, dict):
        raise ExtractionError(f"expected mapping in {source.path}")
    if {"CalculatedFields", "Sheets"} <= set(doc):
        return parse_dashboard(source, doc)
    if "dashboards" in doc:
        found = []
        for dashboard_id, definition in sorted(doc["dashboards"].items()):
            found.append(
                record(
                    source,
                    f"dashboards.{dashboard_id}",
                    "dashboard-package",
                    dashboard_id,
                    definition,
                )
            )
            for index, dataset in enumerate(definition.get("dependsOn", {}).get("datasets", [])):
                found.append(
                    record(
                        source,
                        f"dashboards.{dashboard_id}.dependsOn.datasets[{index}]",
                        "dataset-reference",
                        str(dataset),
                        {"dashboard": dashboard_id},
                    )
                )
        return found, []
    found = []
    for path, key, value in walk(doc):
        if isinstance(value, str) and re.search(r"\bselect\b.+\bfrom\b", value, re.I | re.S):
            category = expression_category(key, value)
            if category == "calculated-field":
                category = "embedded-sql-expression"
            found.append(record(source, path, category, key, {"expression": value}))
        elif isinstance(value, dict) and {"Name", "Type"} <= set(value):
            name = str(value["Name"])
            category = expression_category(name, "")
            found.append(
                record(
                    source,
                    path,
                    "source-field" if category == "calculated-field" else category,
                    name,
                    value,
                )
            )
    skipped = (
        []
        if found
        else [
            {
                "source_file": source.path,
                "source_path": "$",
                "reason": "valid YAML contains no supported analytical structures",
            }
        ]
    )
    return found, skipped


def source_files(manifest: dict[str, Any], roots: dict[str, Path]) -> list[SourceFile]:
    files = []
    for source in manifest["sources"]:
        source_id = source["source_id"]
        if source_id not in roots:
            raise ExtractionError(f"missing --source-root for {source_id}")
        verify_repository(source, roots[source_id])
        for selected in source["selected_files"]:
            if selected["path"] in {source["licence_source_path"], "NOTICE"}:
                continue
            path = roots[source_id] / selected["path"]
            if not path.is_file():
                raise ExtractionError(f"missing pinned file: {path}")
            files.append(
                SourceFile(
                    source_id,
                    source["repository"],
                    source["pinned_commit"],
                    selected["path"],
                    selected["git_blob_sha1"],
                    path,
                )
            )
    return files


def build_inventory(manifest: dict[str, Any], roots: dict[str, Path]) -> dict[str, Any]:
    entities, unsupported, parsed = [], [], []
    for source in source_files(manifest, roots):
        found, skipped = parse_source(source)
        entities.extend(found)
        unsupported.extend(skipped)
        parsed.append(f"{source.source_id}:{source.path}")
    entities.sort(key=lambda item: item["inventory_id"])
    ids = [item["inventory_id"] for item in entities]
    if not entities or len(ids) != len(set(ids)):
        raise ExtractionError("empty inventory or duplicate unstable inventory IDs")
    return {
        "schema_version": VERSION,
        "inventory_id": "aws-cudos-upstream-inventory-v1",
        "parsed_files": sorted(parsed),
        "entities": entities,
        "unsupported_structures": sorted(
            unsupported, key=lambda item: (item["source_file"], item["source_path"], item["reason"])
        ),
    }


def signature(item: dict[str, Any]) -> str:
    category, raw = item["category"], item["raw_definition"]
    expression_categories = {
        "calculated-field",
        "charge-classification",
        "commitment-calculation",
        "comparison-expression",
        "period-expression",
        "recommendation-candidate",
        "service-grouping",
        "embedded-sql-expression",
        "documented-sql-expression",
    }
    if category in expression_categories:
        return canonical({"category": category, "expression": raw.get("expression", raw)})
    if category == "dashboard-visual":
        return canonical(
            {
                "category": category,
                "visual_type": raw["visual_type"],
                "fields": raw["field_references"],
            }
        )
    if category == "drilldown":
        return canonical(
            {
                "category": category,
                "hierarchy_type": raw["hierarchy_type"],
                "columns": raw["columns"],
            }
        )
    if category == "filter-group":
        filters = [
            {"type": entry["type"], "fields": field_refs(entry["definition"])}
            for entry in raw["filters"]
        ]
        return canonical({"category": category, "filters": filters})
    return canonical({"category": category, "definition": raw})


def build_catalogue(inventory: dict[str, Any]) -> dict[str, Any]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for item in inventory.get("entities", []):
        grouped.setdefault(signature(item), []).append(item)
    concepts = []
    for semantic, members in grouped.items():
        members.sort(key=lambda item: item["inventory_id"])
        first = members[0]
        digest = hashlib.sha256(semantic.encode()).hexdigest()[:16]
        concepts.append(
            {
                "concept_id": f"{first['category']}:{slug(first['raw_name'])}:{digest}",
                "category": first["category"],
                "name": first["raw_name"],
                "inventory_ids": [item["inventory_id"] for item in members],
            }
        )
    concepts.sort(key=lambda item: item["concept_id"])
    valid = {item["inventory_id"] for item in inventory["entities"]}
    if any(
        not item["inventory_ids"] or not set(item["inventory_ids"]) <= valid for item in concepts
    ):
        raise ExtractionError("semantic record without valid inventory references")
    return {
        "schema_version": VERSION,
        "catalogue_id": "aws-cudos-semantics-v1",
        "inventory_id": inventory["inventory_id"],
        "content_sha256": hashlib.sha256(canonical(concepts).encode()).hexdigest(),
        "concepts": concepts,
    }


def report(inventory: dict[str, Any], catalogue: dict[str, Any]) -> str:
    raw, semantic = (
        Counter(item["category"] for item in inventory["entities"]),
        Counter(item["category"] for item in catalogue["concepts"]),
    )
    declared_calculations = sum(
        item["source_file"] == "dashboards/cudos/CUDOS-v5-definition.yaml"
        and item["source_path"].startswith("CalculatedFields[")
        for item in inventory["entities"]
    )
    raw_drilldowns = raw.get("drilldown", 0)
    semantic_drilldowns = semantic.get("drilldown", 0)
    lines = [
        "# AWS CUDOS semantic extraction report",
        "",
        "Generated from verified files in clean checkouts of the two pinned repositories.",
        "This is a research inventory, not an implementation backlog or formula adoption.",
        "",
        f"Parsed pinned files: {len(inventory['parsed_files'])}",
        f"Raw upstream entities: {len(inventory['entities'])}",
        f"Declared CUDOS calculated fields: {declared_calculations}",
        f"Drilldown hierarchies: {raw_drilldowns} raw / {semantic_drilldowns} semantic",
        f"Unsupported or skipped structures: {len(inventory['unsupported_structures'])}",
        f"Entities deduplicated: {len(inventory['entities']) - len(catalogue['concepts'])}",
        f"Final semantic concepts: {len(catalogue['concepts'])}",
        f"Catalogue content SHA-256: `{catalogue['content_sha256']}`",
        "",
        "## Raw entities by category",
        "",
    ]
    lines += [f"- `{name}`: {raw[name]}" for name in sorted(raw)]
    lines += ["", "## Semantic concepts by category", ""] + [
        f"- `{name}`: {semantic[name]}" for name in sorted(semantic)
    ]
    lines += ["", "## Unsupported or skipped structures", ""]
    lines += [
        f"- `{item['source_file']}:{item['source_path']}` — {item['reason']}"
        for item in inventory["unsupported_structures"]
    ] or ["- None."]
    lines += [
        "",
        "## Deduplication rules",
        "",
        "- Calculated expressions deduplicate only when category and expression are identical.",
        "- Visuals deduplicate by visual type and referenced fields, not display title.",
        "- Filter groups deduplicate by filter type and referenced fields, not sheet scope.",
        "- Other entities require identical structured definitions.",
        "- Every semantic concept links to one or more stable upstream inventory IDs.",
        "",
        "## Parser limitations",
        "",
        "- QuickSight visuals are summarized to type and field references.",
        "- Drilldowns preserve hierarchy type and ordered columns; empty runtime "
        "filters are ignored.",
        "- Layout, styling, and presentation-only settings are not semantic inputs.",
        "- Markdown is contextual unless it contains a fenced SQL query.",
        "- CloudFormation tags are loaded as inert data and never executed.",
        "",
    ]
    return "\n".join(lines)


def write_outputs(
    manifest_path: Path,
    roots: dict[str, Path],
    inventory_path: Path,
    catalogue_path: Path,
    report_path: Path,
) -> None:
    inventory = build_inventory(load_manifest(manifest_path), roots)
    catalogue = build_catalogue(inventory)
    inventory_path.write_text(
        json.dumps(inventory, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8"
    )
    catalogue_path.write_text(
        json.dumps(catalogue, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8"
    )
    report_path.write_text(report(inventory, catalogue), encoding="utf-8")


def parse_roots(values: list[str]) -> dict[str, Path]:
    roots = {}
    for value in values:
        if "=" not in value:
            raise ExtractionError("--source-root must use SOURCE_ID=PATH")
        source_id, path = value.split("=", 1)
        roots[source_id] = Path(path).resolve()
    return roots


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("manifest", type=Path)
    parser.add_argument("inventory", type=Path)
    parser.add_argument("catalogue", type=Path)
    parser.add_argument("report", type=Path)
    parser.add_argument("--source-root", action="append", default=[])
    args = parser.parse_args()
    write_outputs(
        args.manifest.resolve(),
        parse_roots(args.source_root),
        args.inventory,
        args.catalogue,
        args.report,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
