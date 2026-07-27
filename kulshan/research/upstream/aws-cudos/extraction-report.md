# AWS CUDOS semantic extraction report

Generated from verified files in clean checkouts of the two pinned repositories.
This is a research inventory, not an implementation backlog or formula adoption.

Parsed pinned files: 12
Raw upstream entities: 2481
Unsupported or skipped structures: 3
Entities deduplicated: 1253
Final semantic concepts: 1228
Catalogue content SHA-256: `76b5b809f0998946249391954c6dfcb872effb081d74a360d34d38f1ae90bed9`

## Raw entities by category

- `calculated-field`: 239
- `charge-classification`: 44
- `commitment-calculation`: 81
- `comparison-expression`: 7
- `dashboard-package`: 1
- `dashboard-sheet`: 19
- `dashboard-visual`: 407
- `dataset`: 3
- `dataset-definition`: 3
- `dataset-reference`: 3
- `drilldown`: 279
- `filter-control`: 54
- `filter-group`: 1263
- `parameter`: 40
- `period-expression`: 26
- `recommendation-candidate`: 5
- `service-grouping`: 4
- `sql-view`: 3

## Semantic concepts by category

- `calculated-field`: 185
- `charge-classification`: 38
- `commitment-calculation`: 64
- `comparison-expression`: 7
- `dashboard-package`: 1
- `dashboard-sheet`: 19
- `dashboard-visual`: 404
- `dataset`: 3
- `dataset-definition`: 3
- `dataset-reference`: 1
- `drilldown`: 1
- `filter-control`: 54
- `filter-group`: 372
- `parameter`: 40
- `period-expression`: 26
- `recommendation-candidate`: 5
- `service-grouping`: 2
- `sql-view`: 3

## Unsupported or skipped structures

- `cid/builtin/core/data/queries/shared/cur.yaml:$` — valid YAML contains no supported analytical structures
- `data-exports/README.md:$` — documentation context contains no fenced SQL
- `data-exports/deploy/cur-aggregation.yaml:$` — valid YAML contains no supported analytical structures

## Deduplication rules

- Calculated expressions deduplicate only when category and expression are identical.
- Visuals deduplicate by visual type and referenced fields, not display title.
- Filter groups deduplicate by filter type and referenced fields, not sheet scope.
- Other entities require identical structured definitions.
- Every semantic concept links to one or more stable upstream inventory IDs.

## Parser limitations

- QuickSight visuals are summarized to type and field references.
- Layout, styling, and presentation-only settings are not semantic inputs.
- Markdown is contextual unless it contains a fenced SQL query.
- CloudFormation tags are loaded as inert data and never executed.
