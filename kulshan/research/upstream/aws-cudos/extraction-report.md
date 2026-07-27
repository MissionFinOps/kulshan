# AWS CUDOS semantic extraction report

Generated from verified files in clean checkouts of the two pinned repositories.
This is a research inventory, not an implementation backlog or formula adoption.

Parsed pinned files: 12
Raw upstream entities: 2481
Declared CUDOS calculated fields: 399
Drilldown hierarchies: 279 raw / 51 semantic
Unsupported or skipped structures: 3
Entities deduplicated: 1203
Final semantic concepts: 1278
Catalogue content SHA-256: `af0aa5df2e1a4e4a648bfcd0f506f351171c0b89f5117f27299d981e3ae887b5`

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
- `drilldown`: 51
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
- Drilldowns preserve hierarchy type and ordered columns; empty runtime filters are ignored.
- Layout, styling, and presentation-only settings are not semantic inputs.
- Markdown is contextual unless it contains a fenced SQL query.
- CloudFormation tags are loaded as inert data and never executed.
