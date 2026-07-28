# Reckoner canonical cost semantics (PR 1)

PR 1 defines a renderer-neutral DuckDB relation and qualified metric registry. It does not add query commands, cache materialization, rendering, or invoice reconciliation. Existing CLI and public JSON routes remain unchanged.

## Relation and sources

`Source schema -> schema adapter -> canonical DuckDB relation -> registered metric expression` is shared by explicit local Parquet files and manifest-pinned S3 Parquet objects. Locations cannot contain globs. The S3 context requires the caller AWS session and closes its DuckDB connection.

The relation preserves payer/account identity, half-open usage and billing times, service/location fields, original charge type, normalized charge category, commitment references, currency, quantity, and separate additive cost components. It deliberately excludes tags and Cost Categories.

Supported detection is deterministic: legacy flat AWS CUR, AWS Data Exports/CUR 2.0 markers, and AWS FOCUS 1.0. FOCUS versions are not treated as interchangeable. Ambiguous or unsupported signatures fail. Schema metadata is exposed as `source_schema` and `source_schema_version`.

## Qualified metrics

Version 1.0 implements `unblended-cost`, `net-unblended-cost`, `blended-cost`, `amortized-cost`, `effective-cost` (AWS FOCUS 1.0 only), `public-on-demand-cost`, `credits`, `refunds`, `support`, `taxes`, `savings-plan-fees`, `reserved-instance-fees`, and `usage-quantity` when required fields exist.

`invoiced-cost`, `net-amortized-cost`, and `unused-commitment-cost` remain unavailable. CUR cannot by itself guarantee final invoice reconciliation. `effective-cost` is never an alias for amortized cost. Explicit requests never fall back. Compatibility-only `auto` discloses its order, missing preferred components, selected metric, and reason.

## Charge and currency rules

Classification version 1.0 preserves the raw charge type and distinguishes usage, commitment fees, covered or discounted usage, unused commitment, credit, refund, tax, support, Marketplace, discount, fee, adjustment, and unknown. Unknown values remain unknown.

Source currency is preserved and never converted. Null or malformed currency fails. Multiple currencies fail unless currency is a grouping, in which case results remain separated.

## Provenance and limitations

CUDOS amortized and public On-Demand semantics are adapted from the exact pinned `summary_view.sql` blob and recorded in `provenance-records.json`. Golden fixtures qualify their behavior. The formulas provide analytical allocation, not proof of a finalized AWS invoice, and this PR does not claim full CUDOS parity.

Existing cost commands still use their compatibility paths; migrating them is deliberately deferred until it can preserve their public output contracts without broadening PR 1.