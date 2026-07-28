# CUR catalogue and onboarding (PR 2)

PR 2 adds a workspace-local metadata control plane at `cur-catalog.db`. It records export identity, destination, source provider, schema era, immutable manifest versions, object keys and sizes, period coverage, and independent delivery/access/schema/payer/settlement/cache states.

The catalogue is metadata-only. It does not download CUR files, build DuckDB cache tables, scan recursive S3 paths, or infer final invoice settlement. Each manifest is deterministically identified from its export, sorted object metadata, and sorted periods. Earlier manifests remain available for auditability.

Existing read-only discovery is reused for Data Exports and legacy CUR. The new commands are:

```text
kulshan cur catalog status [--json]
kulshan cur catalog manifests
kulshan cur catalog doctor
```

`status` reports coverage and state independently. `doctor` checks catalogue referential and metadata consistency without reading billing objects. Cache state remains `not-built` until a later cache PR.

PR 2 deliberately defers S3 byte estimation, cache consent/materialization, source planning, query execution, terminal exploration, and saved queries to later boundaries.