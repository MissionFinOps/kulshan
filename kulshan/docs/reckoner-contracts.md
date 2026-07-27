# Reckoner Engine contracts

The planned Reckoner Engine will provide deterministic, renderer-neutral cost
investigation contracts. PR 0 establishes only the research pins, provenance
rules, request/result schemas, registry vocabulary, execution-source metadata,
trust-inspection shape, and safe declarative module schema.

PR 0 does **not** provide a usable query engine. It does not implement cost
formulas, CUR normalization, caches, SQL compilation or execution, charts,
guided exploration, reports, CLI query commands, or AI behavior. Existing CLI
and public JSON paths do not use these contracts.

## Pinned CUDOS research

The research package under `research/upstream/aws-cudos/` pins:

- `cloud-intelligence-dashboards-framework` at
  `f9e36d88c47709f10e8fa784ad11d5cc0e728021` under MIT-0.
- `cloud-intelligence-dashboards-data-collection` at
  `d7945a36c3d9dc166d57752d66edfeb425f44a17` under Apache-2.0.

`upstream-manifest.json` records exact repositories, commits, licence paths,
selected files, and Git blob hashes. Run the fail-closed verifier with:

```powershell
python scripts/research/verify_aws_cudos_upstream.py research/upstream/aws-cudos/upstream-manifest.json
```

The verifier fetches public sources into a temporary directory, checks the
exact commit and every selected blob, and executes no upstream code.

No protectable upstream implementation is copied in PR 0. Consequently there
is no new third-party notice claiming adaptation. Future copied or adapted
formula implementations must create a record matching
`provenance-schema.json`, including source locator, blob hash, destination,
material changes, formula identity/version, golden fixture, and notice duty.

## Semantic deduplication

The inventory and catalogue are regenerated directly from verified detached
checkouts; there is no manually maintained semantic intermediate:

```powershell
python scripts/research/extract_aws_cudos_semantics.py `
  research/upstream/aws-cudos/upstream-manifest.json `
  research/upstream/aws-cudos/upstream-inventory.json `
  research/upstream/aws-cudos/semantic-catalogue.json `
  research/upstream/aws-cudos/extraction-report.md `
  --source-root aws-cudos-framework=C:\path\to\framework `
  --source-root aws-cudos-data-collection=C:\path\to\data-collection
```

The command verifies repository identity, commits, and selected blobs before it
parses dashboard sheets, datasets, visuals, calculated fields, parameters,
filter groups and controls, drilldowns, SQL views, and supported aggregation
structures. `upstream-inventory.json` preserves exact document paths and blob
provenance. Every deduplicated concept refers to one or more inventory IDs.
Unsupported structures and parser limitations are disclosed in the report.

Calculated fields deduplicate only by identical categorized expressions.
Visual variants deduplicate by visual type and field references; presentation
layout and styling do not create implementation work. This inventory and the
semantic catalogue remain research evidence, not adopted Kulshan formulas.

## Semantic acceptance notes

`CUDOS-v5-definition.yaml` declares 399 top-level calculated fields. The inventory
preserves all 399: 239 remain in the generic `calculated-field` category and 160
are classified into charge, commitment, comparison, period, recommendation, or
service-grouping categories. The category count is not a declaration count.

The dashboard also declares 279 column hierarchies. These are inventoried as
drilldowns with hierarchy type and ordered columns. They reduce to 51 semantic
hierarchies; 211 implicit date hierarchies intentionally share one semantic,
while distinct explicit column paths remain separate. Empty QuickSight runtime
`DrillDownFilters` arrays are not treated as drilldown definitions.
## PR 0 evidence levels

PR 0 deliberately distinguishes five levels:

1. Pinned upstream sources are exact, licence-checked Git objects.
2. The machine-generated upstream inventory records source entities without adoption.
3. The semantic catalogue deduplicates research concepts with inventory traceability.
4. Kulshan registry descriptors reserve stable planned identifiers.
5. Implemented Kulshan formulas remain empty in PR 0.

## Versioning and compatibility

- `QuerySpec`, `QueryResult`, provenance, and module schemas begin at `1.0`.
- Loaders reject unknown fields and unsupported versions. Saved definitions
  fail closed instead of silently changing meaning.
- Additive optional fields may be introduced within a major version only when
  older readers can safely ignore them after an explicit reader-policy update.
- Removing a field, changing meaning or type, changing validation, or changing
  a stable registry identifier requires a new major schema version.
- Registry IDs are machine-stable. Deprecated IDs remain readable through a
  documented alias period before removal in a major version.
- Serialization uses UTF-8 JSON-compatible types, stable string enum values,
  explicit nulls where the schema permits them, and separate SQL bindings.
- Existing Kulshan public JSON contracts are unchanged and are not routed
  through Reckoner in PR 0.

## QuerySpec v1

`QuerySpec` describes a metric, named or half-open custom period, up to three
groupings, filters, exclusions, comparison, sort, bounded limit, visualization
preference, execution-source request, and output format. It cannot contain SQL,
Python, credentials, AWS sessions, rows, or executable hooks.

Dynamic dimensions use validated `tag:KEY` and `cost-category:KEY` identifiers.
Custom periods use `start <= usage_time < end`.

## QueryResult v1

The result envelope requires the resolved query, resolved primary period, and
selected execution source. Before execution, columns, rows, totals, comparison
data, formulas, manifests, cache partitions, freshness, SQL, bindings, and
execution statistics may be absent or empty.

Machine-stable fields include schema versions, identifiers, enum values,
boundaries, column IDs, formula IDs/versions, source IDs, fingerprints, and
counts. `display_metadata` is explicitly human-display metadata. Manifest URIs,
bindings, row values, account/resource dimensions, and SQL literals may require
redaction; bindings remain separate from generated SQL.

## Registries and availability

Metric registry entries in PR 0 are **planned descriptors**, not formulas.
Their implementation status is `planned`, formula version is absent, and their
availability rule says they cannot execute. `auto` is compatibility-only and
must resolve to an explicit metric later.

Dimension and period registries likewise preserve stable planned vocabulary
without physical expressions or AWS period discovery. Each dimension declares
its supported operators, sensitivity, schema families, cardinality, cache
profile, normalization rule, and drilldown metadata.

## Execution and trust inspection

Execution-source contracts represent `auto`, `cache`, `local`, and `s3`.
Planner-decision metadata can explain selection reason, cache coverage, local
availability, S3 estimate and confirmation requirements, or an unsatisfied
query requirement. It does not choose a source in PR 0.

`TrustInspection` is the future structured payload for `--explain`,
`--show-sql`, and `--show-sources`. It keeps generated SQL and bound values
separate and carries cost basis, formula identity, boundaries, groupings,
predicates, source, cache/freshness, limitations, manifests, fingerprints,
provenance references, and S3 bytes. No unfinished CLI flags are exposed.

## Declarative modules

PR 0 modules use strict JSON and the standard-library JSON parser. True YAML
module support is deferred until a safe loader and dependency are justified.
Module files can contain only validated metadata and `QuerySpec` defaults;
SQL, Python, shell commands, credentials, customer data, and executable
expressions are rejected. The included `.json` module is a schema fixture, not
a functional analysis module. PyYAML is a development-only dependency used by
the pinned upstream research extractor, not the module loader or runtime.

Later PRs may consume these contracts only after they add separately reviewed
formula, normalization, planning, execution, or rendering behavior.
