# Investigation Packs Inspired by CID

This document is an implementation plan for using AWS Cloud Intelligence Dashboards (CID) as inspiration without depending on CID infrastructure.

Read `docs/product/MTTE.md` and `docs/product/LOCAL_EVIDENCE_ENGINE.md` first.

## Positioning

CID is the dashboard. Kulshan is the local detective.

CID proves the question set: cost overview, KPIs, service movement, account movement, usage type movement, untagged spend, commitment posture, and service-specific deep dives.

Kulshan should reuse that question catalog locally:

```text
Local CUR / Data Exports Parquet files
  -> DuckDB SQL views
  -> investigation packs
  -> evidence packet
  -> terminal brief
```


Current implemented reality:

- Experimental local Parquet only.
- Accepts a local `.parquet` file or a local directory containing `.parquet` files.
- Does not support `s3://` paths.
- Does not discover AWS Data Exports.
- Does not list S3 buckets or prefixes.
- Does not query Athena or use Glue.
- Requires no AWS IAM permissions for the investigation command.

Future / not implemented yet:

- S3 CUR/Data Export reads.
- AWS Data Export discovery.
- S3 bucket/prefix listing.
- Glue/Athena query support.
- Markdown and JSON investigation output.
Do not copy CID's deployment model:

```text
Glue
Athena
QuickSight
SPICE
dashboard deployment
daemon
SaaS control plane
```

## Proposed CLI wedge

Build a proof-of-concept local CUR query engine.

Implemented commands:

```bash
kulshan cur validate --path <local-parquet-file-or-dir>
kulshan cur schema --path <local-parquet-file-or-dir>
kulshan investigate ec2 --cur <local-parquet-file-or-dir> --month YYYY-MM
```

Future / not implemented yet:

```bash
kulshan cur top-services --path <local-parquet-file-or-dir> --month YYYY-MM
kulshan investigate ec2 --cur s3://billing-bucket/prefix/ --month YYYY-MM
```


Local-only onboarding:

1. Export, download, or sync CUR/Data Export Parquet files to a local directory such as `./cur/`.
2. Validate the local files:

```bash
kulshan cur validate --path ./cur/
```

3. Investigate EC2 movement for a billing month:

```bash
kulshan investigate ec2 --cur ./cur/ --month YYYY-MM
```

IAM note: current local-only mode requires no AWS IAM permissions for the investigation command. S3 sync and future Athena/S3 discovery modes would require separate AWS permissions and are not implemented yet.
Goal:

Prove Kulshan can query CUR / Data Exports Parquet locally and produce a simple EC2 delta brief.

Do not add dashboard, daemon, GPU, LLM, MCP, Slack, Jira, Athena dependency, QuickSight dependency, or CID dependency.

## Proposed implementation structure

This structure belongs in the Kulshan CLI repository, not necessarily this website repository.

```text
kulshan/
  cur/
    __init__.py
    validate.py
    schema.py
    top_services.py
    duckdb_engine.py
    source.py
  investigations/
    __init__.py
    registry.py
    views/
      cost_overview.sql
      service_deltas.sql
      account_deltas.sql
      resource_deltas.sql
      usage_type_deltas.sql
      untagged_spend.sql
      commitment_health.sql
    packs/
      __init__.py
      ec2_investigation.py
      rds_investigation.py
      data_transfer.py
      commitments.py
      ownership.py
  investigate/
    __init__.py
    brief.py
    evidence.py
    commands.py
```

## First SQL view stubs

The first implementation should create SQL view files with stable names and comments, even if some start as minimal queries.

Required initial stubs:

- `cost_overview.sql`
- `service_deltas.sql`
- `account_deltas.sql`
- `resource_deltas.sql`
- `usage_type_deltas.sql`
- `untagged_spend.sql`
- `commitment_health.sql`

Each view should:

- Query a normalized CUR relation, not raw source paths directly.
- Accept period boundaries through the calling layer.
- Return deterministic numeric columns.
- Avoid business narrative.
- Avoid LLM-generated SQL.

## Pack registry

The pack registry should map a pack name to SQL views, required inputs, outputs, and evidence-contract sections.

Example shape:

```text
cudos-lite:
  views:
    - cost_overview
    - service_deltas
    - account_deltas
    - usage_type_deltas
    - untagged_spend
  outputs:
    - current_period_cost
    - previous_period_cost
    - delta
    - top_services
    - top_accounts
    - untagged_spend
```

## First command

Start with the EC2 investigation command:

```bash
kulshan investigate ec2 --cur <local-parquet-file-or-dir> --month YYYY-MM
```

The first version should reuse the local SQL engine and evidence contract, then emit the brief defined in `docs/product/MTTE.md`.

## Non-goals

- Do not build dashboards.
- Do not require CID.
- Do not require Athena.
- Do not require Glue.
- Do not require QuickSight or SPICE.
- Do not add a daemon.
- Do not add Slack, Jira, MCP, or chat.
- Do not use LLMs for SQL, accounting, joins, or owner primitives.

## Rule

AWS CID is the proven question set.

Kulshan is local execution plus an evidence brief.
