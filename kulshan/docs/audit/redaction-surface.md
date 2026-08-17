# Kulshan Redaction Surface Audit

> **NOTE:** Implementation plan based on this audit is at `docs/design/privacy-foundation-0.5.1.md`.
> This audit remains a valid reference for the state of the codebase at commit `770cad6a`.

**Audited commit:** `770cad6a49f206b57a0ce2c43b9cfe1bba09b700`
**Version string:** `0.5.0` (from `src/kulshan/__version__.py`)
**Audit date:** 2026-08-15
**Scope:** Every code path through which a customer-identifying string can reach a user-visible or written artifact.

---

## 1. Identifier Inventory

### 1.1 AWS Account IDs (12-digit)

| Field/column | Source | Entry module + function | Output paths reached |
|---|---|---|---|
| `account_id` (Finding field) | Cost Explorer API, checks packs | `adapter.py:182` (`adapt()` — maps from `account_id` or `account` alias) | JSON, HTML, SARIF, CSV, terminal, history SQLite, MCP |
| `account_id` (session-level) | STS GetCallerIdentity | `session.py:60` (`get_account_id()`) | All renderers via `cli.py:683`, history SQLite `scans.account_id` |
| `payer_account_id` | CUR `bill_payer_account_id` column; workspace config TOML | `workspace/payer_binding.py:93` (`extract_payer_from_cur()`); `workspace/config.py` (`WorkspaceAwsConfig.payer_account_id`) | History SQLite `scans.payer_account_id`, workspace TOML on disk, terminal display |
| `expected_session_account_id` | User-configured in workspace TOML | `workspace/config.py` (`AwsConnection.expected_session_account_id`) | Workspace TOML on disk, history `scan_connections.session_account_id` |
| `linked_account` / `payer_account` | CUR Parquet columns | `reckoner/cost/semantics.py:131-132` (CUR_FIELDS mapping) | Reckoner query results (JSON, CSV, markdown, terminal) |
| `DeltaRow.name` (when grouped by account) | CUR Parquet; `analyze/cost.py:~line 100` (`_delta_rows()` with `"account_id"` dimension) | `analyze/cost.py` → `analyze/models.py` DeltaRow | analyze export JSON/markdown/terminal, MCP `analyze_cost` tool |

**Classification:** Customer-identifying.

### 1.2 Account Names and Aliases

| Field/column | Source | Entry module + function | Output paths reached |
|---|---|---|---|
| `linked_account_name` | CUR column `line_item_usage_account_name` | `reckoner/cost/semantics.py:133` (CUR_FIELDS); FOCUS `SubAccountName` at line 193 | Reckoner query results when grouped by `account-name` |

**Classification:** Customer-identifying.

### 1.3 Organizational Unit Names and Paths

No OU name or path field exists in the current codebase. Cost Explorer API responses can include OU-based linked account groupings, but the code does not parse or surface them.

**Classification:** Not present in code at audited commit.

### 1.4 Cost Allocation Tag Keys

| Field/column | Source | Entry module + function | Output paths reached |
|---|---|---|---|
| `resource_tags_user_owner` | CUR Parquet | `cur/schema.py:80` (`resolve_cur_columns()` → `owner_tag`) | `analyze/models.py` `TagCoverage.owner_values`; analyze export |
| `resource_tags_user_team` | CUR Parquet | `cur/schema.py:85` → `team_tag` | `TagCoverage.team_values` |
| `resource_tags_user_application` | CUR Parquet | `cur/schema.py:86-90` → `application_tag` | `TagCoverage.application_values` |
| `resource_tags_user_cost_center` | CUR Parquet | `cur/schema.py:91` → `cost_center_tag` | `TagCoverage.cost_center_values` |
| `resource_tags_user_environment` | CUR Parquet | `cur/schema.py:92` → `environment_tag` | `TagCoverage.environment_values` |

The **key names** are hardcoded patterns (`resource_tags_user_*`). The CUR may contain arbitrary tag key columns; only those matching the patterns above are read.

**Classification:** Mixed. Key names themselves are customer-defined vocabulary (e.g. `resource_tags_user_cost_center` is standard; a tag like `resource_tags_user_jira_project` would be customer-identifying). Only the fixed set above is currently parsed.

### 1.5 Cost Allocation Tag Values

| Field/column | Source | Entry module + function | Output paths reached |
|---|---|---|---|
| Values from tag columns listed in 1.4 | CUR Parquet rows | `analyze/cost.py` and `analyze/ec2.py` (DuckDB queries selecting tag columns) | `TagCoverage.*_values` lists → analyze export JSON/markdown/terminal; MCP `analyze_ec2` tool |

**Classification:** Customer-identifying. Tag values are unbounded free text (team names, application names, cost centre codes).

### 1.6 Cost Category Names and Rule Values

Not present. The CUR 2.0 marker set in `reckoner/cost/semantics.py:265` includes `"cost_category"` as a detection signal, but no code reads or surfaces cost category values.

**Classification:** Not present in code at audited commit.

### 1.7 Resource IDs and ARNs

| Field/column | Source | Entry module + function | Output paths reached |
|---|---|---|---|
| `resource_arn` (Finding field) | AWS API responses via checks packs; adapted from `resource_id` alias | `adapter.py:184`; `models.py:362` | JSON, HTML, SARIF (as `fullyQualifiedName`), CSV (`resource_id` column), terminal (in finding detail), MCP compact findings |
| `resource_id` (CUR column) | CUR Parquet `line_item_resource_id` | `cur/schema.py:76`; `reckoner/cost/semantics.py:162` | Reckoner query results, cost attribution `attribution.resource_id`, Finding `resource_arn` field |
| `reservation_id` / `savings_plan_id` | CUR Parquet | `reckoner/cost/semantics.py:163-164` (CUR_FIELDS) | Reckoner canonical relation; not currently surfaced in renderers but available in query results |
| Remediation snippet placeholders | `remediation.py:18-60` templates with `{resource_id}`, `{resource_arn}` | Formatted via `remediation.py` at finding construction time | JSON, HTML, SARIF, CSV `remediation_snippet` |

**Classification:** Customer-identifying. Instance IDs, bucket names, function ARNs are all customer-scoped.

### 1.8 Usage Account and Payer Account Identifiers

Covered in 1.1 above. The CUR schema maps:
- `line_item_usage_account_id` → `account_id` semantic field (`cur/schema.py:77`)
- `bill_payer_account_id` → payer extraction (`workspace/payer_binding.py:93`)

### 1.9 Savings Plan ARNs and Reserved Instance IDs

| Field/column | Source | Entry module + function | Output paths reached |
|---|---|---|---|
| `savings_plan_id` | CUR `savings_plan_savings_plan_a_r_n` | `reckoner/cost/semantics.py:164` | Canonical relation columns; available to Reckoner queries |
| `reservation_id` | CUR `reservation_reservation_a_r_n` | `reckoner/cost/semantics.py:163` | Same |

These are not currently exposed in any default report output. They become visible only via explicit Reckoner `--grouping commitment` queries.

**Classification:** Customer-identifying (contain the 12-digit account ID).

### 1.10 Region and Availability Zone Values

| Field/column | Source | Entry module + function | Output paths reached |
|---|---|---|---|
| `region` (Finding field) | AWS API responses | `adapter.py:183`; `models.py:361` | All output renderers |
| `region` (CUR) | `product_region` | `cur/schema.py:82`; `reckoner/cost/semantics.py:152` | Reckoner results, analyze `top_regions` |
| `availability_zone` | CUR `line_item_availability_zone` | `cur/schema.py:82` (fallback); `reckoner/cost/semantics.py:153` | Reckoner results (grouping `availability-zone`) |

**Classification:** AWS-standard vocabulary. Region codes (`us-east-1`) and AZ identifiers (`us-east-1a`) are not customer-identifying.

### 1.11 User-Supplied Strings Echoed into Output

| String | Source | Where echoed |
|---|---|---|
| `--profile` CLI argument | CLI | Not echoed into reports; stored in workspace TOML and history `scan_connections.profile` |
| `--role-arn` CLI argument | CLI | Stored in workspace TOML (`AwsConnection.role_arn`); history `scan_connections.role_arn`; partially displayed in terminal error messages (`cli.py:716-717` — already redacted via `redact_arn`) |
| `--cur-export` CLI argument | CLI | Stored in workspace TOML; contains S3 URI or export ARN which may embed account ID |
| Workspace name | CLI `--workspace` | Displayed in terminal prompts and stored in history; user-chosen, unlikely identifying |
| Connection name | Workspace TOML | Stored in history `scan_connections.connection_name`; user-chosen |

---

## 2. Output Path Inventory

### 2.1 stdout Renderers

| Path | Module | Entry point | Formats |
|---|---|---|---|
| Terminal report | `report/terminal.py` | `render_report()` | Rich-formatted terminal output |
| Reckoner terminal | `reckoner/terminal.py` | `render_result()` | Rich-formatted table |
| Analyze terminal | `analyze/export.py` | `cost_brief_to_terminal()`, `ec2_brief_to_terminal()` | Plain text |
| JSON to stdout | `cli.py:117-121` | `_emit_output()` with `fmt="json"` and no `--output` | Raw JSON (no redaction when piped to stdout without `-o`) |
| CSV to stdout | `cli.py:87-91` | `_emit_output()` with `fmt="csv"` and no `--output` | CSV text |

**Terminal output is explicitly never redacted** (stated in `redact.py` docstring line 3-4).

**JSON and CSV to stdout (no `-o` flag):** `cli.py:117-121` — JSON payload is constructed with raw `account_id`, and `redact_payload()` is only applied when `output` is a file path AND `show_pii` is False. When `output` is None (stdout), the JSON is emitted **without** redaction regardless of `--show-pii`. This is a gap (see below).

### 2.2 File Writers

| Path | Module | Entry point | Formats | Redaction applied? |
|---|---|---|---|---|
| HTML report | `report/html.py` | `generate_html_report()` via `cli.py:129-141` | HTML | Yes — `redact_account_id()` on account, `redact_payload()` on results and actions |
| JSON report file | `cli.py:106-121` | `_emit_output()` | JSON | Yes when `-o` given — `redact_payload()` applied to entire dict |
| SARIF report file | `report/sarif.py` → `cli.py:93-99` | `to_sarif_json()` | SARIF JSON | Yes — findings and account_id redacted before passing to renderer |
| CSV report file | `report/csv_export.py` → `cli.py:85-91` | `findings_to_csv()` | CSV | **NO** — `findings_to_csv()` receives raw `all_findings`; no `redact_payload()` call before CSV formatting |
| Reckoner renderers | `reckoner/renderers.py` | `render_json()`, `render_csv()`, `render_markdown()` | JSON, CSV, Markdown | **NO** — no redaction hook exists in this path |
| Analyze export | `analyze/export.py` | `export_brief()`, `brief_to_json()`, `brief_to_markdown()` | JSON, Markdown | **NO** — writes `DeltaRow.name` (which may contain account IDs) and `OwnerCandidate.account_id` unredacted |
| Investigate JSON (via MCP) | `mcp_server/tools.py` | `_execute_analyze_cost()`, `_execute_analyze_ec2()` | JSON | **NO** |

### 2.3 Log Output

Logging is sparse. Modules using `logging.getLogger(__name__)`:
- `consolidated.py:26` — logs connection name on failure (`logger.warning("Connection '%s' unavailable: %s", conn_name, e)`)
- `orchestrator.py:12` — logs pack name and finding index on validation failure
- `session.py:66` — fallback region warning (no identifiers)
- `workspace/onboarding.py:52` — logs workspace directory name on re-creation
- `workspace/registry.py:33` — logs registry key corruption (no account IDs)
- `workspace/resolution.py:30` — logs workspace name on failure

**No logger call in the codebase interpolates account IDs, resource ARNs, or tag values into log messages.** The `consolidated.py:105` call logs only the connection name string. Exception messages from `StsVerificationError` may contain the expected and actual account IDs, but these are caught and re-displayed via Rich console with `redact_account_id()` at `cli.py:716-717`.

### 2.4 Exception Messages and Tracebacks

| Location | Content |
|---|---|
| `workspace/payer_binding.py` `InvalidPayerEvidenceError` | Interpolates the invalid payer value (`self.value`) into the message |
| `workspace/payer_binding.py` `MultiplePayerEvidenceError` | Interpolates all payer IDs (`', '.join(payer_ids)`) |
| `workspace/sts.py` `StsVerificationError` | Contains expected and actual account IDs |
| `workspace/onboarding.py` `PayerBindingConflictError` | Contains conflicting payer IDs |

If an unhandled exception propagates to the user or is captured by a crash reporter, these would leak raw account IDs.

### 2.5 Cache, Intermediate, and Temp Files

| Location | Module | Content |
|---|---|---|
| SQLite history database | `history/__init__.py` | `scans.account_id`, `scans.payer_account_id`, `scan_connections.session_account_id`, `scan_connections.role_arn`, `scans.full_result_json` (optionally stores entire JSON payload unredacted) |
| Workspace TOML files | `workspace/config.py` | `payer_account_id`, `expected_session_account_id`, `role_arn`, `cur_export` |
| Reckoner cache (planned) | `reckoner/cache/` directory exists | Undetermined — directory exists but implementation was not found at this commit |
| Atomic write tempfiles | `cli.py:40-53` (`_atomic_write()`) | Transient `.tmp` files in the output directory; cleaned up on success, may persist on crash |

### 2.6 Anything Written Outside the Working Directory

- History SQLite: written to `platformdirs.user_data_dir("Kulshan", "missionfinops") / "history.db"` (`history/__init__.py:22`)
- Workspace TOML: written to platform-specific data directory via `platformdirs`

---

## 3. Existing Redaction Capability

### 3.1 Location

`src/kulshan/redact.py` — 230 lines, fully implemented.

### 3.2 Coverage

| Covered | Not covered |
|---|---|
| AWS 12-digit account IDs (pattern and field-name match) | Tag values (customer team names, app names, cost centres) |
| ARNs (account portion + resource name) | Cost category names |
| Email addresses | DeltaRow.name when it holds an account ID (string, not field-named `account_id`) |
| IPv4 addresses | Reckoner query result row values |
| S3 bucket names | Analyze export output |
| Hostnames | MCP tool output |
| AWS access keys and secret keys | CSV export path (findings passed unredacted) |
| Free-text fields (title, description, recommended_action) — scanned for inline patterns | Workspace TOML on disk |
| Report filenames | History SQLite |

### 3.3 Default State

**On by default** for file-based exports (HTML, JSON with `-o`, SARIF). Disabled by `--show-pii` flag.

**Off for terminal output** — intentional design decision documented in `redact.py` docstring.

**Not wired** for: CSV export, MCP tool responses, Reckoner renderers, analyze export, history persistence.

### 3.4 Determinism

The current redaction is **deterministic but not pseudonymized**. It truncates to last-4-digits or masks with fixed patterns (`XXXX-XXXX-9012`). The same input always produces the same output. However, it is **not a stable pseudonym** — two different accounts ending in the same 4 digits produce the same redacted value, which could collapse grouping/aggregation.

### 3.5 Reachability from CLI

Controlled by `--show-pii` flag on `report` and `convert` commands. No CLI surface for redacting analyze or Reckoner output.

### 3.6 Additional Redaction

`workspace/payer_binding.py:167` — a standalone `_redact_payer()` function (duplicates logic from `redact.py`).
`capabilities.py:325` — `mask_account_id()` function with different masking pattern (`12345***9012`), used only in preflight display.

---

## 4. Architecture Assessment

### 4.1 Single Choke Point?

**No.** There is no single choke point. Output formatting happens independently in multiple locations:

1. `cli.py:_emit_output()` — dispatches to HTML/JSON/SARIF/CSV/terminal renderers
2. `reckoner/renderers.py` — separate JSON/CSV/markdown renderers for query results
3. `analyze/export.py` — separate JSON/markdown/terminal renderers for investigation briefs
4. `mcp_server/tools.py` — `_compact_finding()` and `_json()` format output independently
5. `report/terminal.py` — renders directly to Rich Console

### 4.2 Minimal Function Set for Full Coverage

To guarantee redaction on every output path:

1. `cli.py:_emit_output()` — already partially instrumented; needs CSV gap closed
2. `reckoner/renderers.py:render_json()`, `render_csv()`, `render_markdown()` — 3 functions
3. `reckoner/terminal.py:render_result()` — 1 function
4. `analyze/export.py:export_brief()` — 1 function (dispatches to all format variants)
5. `mcp_server/tools.py:_compact_finding()` and `_execute_preflight()` — 2 functions
6. `history/__init__.py:save_scan()` and `save_consolidated_scan()` — 2 functions (for at-rest storage)

**Minimum touch count: 10 functions across 6 modules.**

### 4.3 Data Structure Shape

Identifiers are carried as:
- **Typed fields** on the `Finding` dataclass (`models.py:358-365`): `account_id`, `region`, `resource_arn`, `resource_type`, `service`
- **Typed fields** on `OwnerCandidate` (`analyze/models.py`): `account_id`, `contact`, `team`
- **Loose dictionaries** in pack results (`results[pack]["findings"]` is `list[dict]`)
- **DataFrame/DuckDB columns** in CUR processing whose key names vary by schema detected at runtime (`reckoner/cost/semantics.py` resolves physical columns to canonical names)
- **`DeltaRow.name`** — a generic `str` field whose semantic meaning depends on the grouping dimension it was produced from

### 4.4 Identifiers Used as Keys/Indexes

| Usage | Location | Impact of substitution |
|---|---|---|
| `account_id` as deduplication key in consolidated reports | `consolidated.py` (fingerprint includes `account_id`) | Pseudonymized value must be stable within a single invocation; otherwise deduplication breaks |
| `account_id` as SQLite index | `history/__init__.py` `idx_scans_account` | History lookups and delta comparison use raw account_id; pseudonymization would break cross-scan correlation |
| `DeltaRow.name` as aggregation group key | `analyze/cost.py` (`_delta_rows()`) | Value is the GROUP BY output; substitution is safe if done after aggregation |
| `fingerprint` computation includes `account` | `models.py:183` (`compute_fingerprint()`) | Pseudonymization before fingerprinting would change finding identity across redacted/unredacted runs |
| Reckoner `QueryResult.rows` dict keys are column names, values are group members | `reckoner/query.py:execute_query()` | Values (e.g. account IDs) appear as row data, not dict keys; safe to substitute post-query |

### 4.5 Pseudonym Mapping Boundaries

A stable pseudonym mapping would need to be held:
- **Per-invocation** for all paths that produce a single coherent output (one report run, one analyze command, one MCP tool call)
- **Across rows within a QueryResult** for Reckoner output (same account must map to same pseudonym)
- **NOT across invocations** — history correlation is already broken by the truncation approach; true pseudonymization would need a persistent salt or stored mapping if cross-run stability is desired

---

## 5. Vocabulary Allowlist Feasibility

### 5.1 Fields Drawing from Bounded, Known Vocabulary

| Field | Vocabulary | Enumerated in code? | Location |
|---|---|---|---|
| `region` | AWS region codes (`us-east-1`, etc.) | No explicit enum. `session.py:get_enabled_regions()` fetches dynamically. | — |
| `service` / `service_name` | AWS service codes (`AmazonEC2`, `AmazonS3`, etc.) | No explicit enum. Cost Explorer returns them. | — |
| `usage_type` | AWS usage type strings (`USE1-NatGateway-Bytes`, etc.) | Not enumerated. | — |
| `operation` | AWS operation strings | Not enumerated. | — |
| `raw_line_item_type` | `Usage`, `Tax`, `Credit`, `Fee`, `RIFee`, `SavingsPlanCoveredUsage`, etc. | Partially enumerated in `CHARGE_CATEGORY_SQL` (`reckoner/cost/semantics.py:375-410`) | `semantics.py:375` |
| `charge_category` | Kulshan canonical enum | Fully enumerated as `ChargeCategory` enum | `reckoner/cost/semantics.py:41-57` |
| `purchase_option` / `pricing_term` | `OnDemand`, `Reserved`, `Savings Plan`, etc. | Not enumerated as constants | — |
| `currency` | ISO 4217 codes | Not enumerated; validated only as non-mixed | — |
| `severity` (Finding) | `critical`, `high`, `medium`, `low`, `info` | Enumerated as `Severity` enum | `models.py` |
| `effort` (Finding) | `trivial`, `low`, `medium`, `high` | Enumerated as `VALID_EFFORT` | `models.py` |
| `risk` (Finding) | `safe`, `low_risk`, `needs_review` | Enumerated as `VALID_RISK` | `models.py` |
| GROUPINGS dimension names | `payer`, `account`, `service`, `region`, etc. | Fully enumerated | `reckoner/cost/semantics.py:673-689` |
| Reckoner grouping column names | `payer_account`, `linked_account`, `service_name`, etc. | Fully enumerated as GROUPINGS values | `reckoner/cost/semantics.py:673-689` |

### 5.2 Vocabularies Enumerated as Constants

- `ChargeCategory` enum: `reckoner/cost/semantics.py:41-57`
- `Severity` enum: `models.py` (5 values)
- `VALID_EFFORT`, `VALID_RISK`: `models.py`
- `GROUPINGS` mapping: `reckoner/cost/semantics.py:673-689`
- `TOOL_ORDER` / `TOOL_LABELS` / `TOOL_ICONS`: `orchestrator.py`
- `PACK_DESCRIPTIONS`: `report/sarif.py:28-39`
- EOL database entries: `checks/age/eol_db.py`

### 5.3 Fields That Are Unbounded Free Text

| Field | Source | Risk |
|---|---|---|
| Tag values (`owner_values`, `team_values`, `application_values`, `cost_center_values`, `environment_values`) | CUR Parquet | High — contain internal team/project names |
| `DeltaRow.name` (when dimension is `account_id`) | CUR/Cost Explorer | High — raw 12-digit account IDs |
| `DeltaRow.name` (when dimension is `usage_type`) | CUR/Cost Explorer | Low-medium — AWS vocabulary but can include region-prefix identifiers |
| `Finding.title` | Pack logic (string interpolation) | Medium — may embed resource names, account IDs |
| `Finding.description` | Pack logic | Medium — same |
| `Finding.recommended_action` / remediation snippets | `remediation.py` templates + pack logic | High — contain `{resource_id}`, `{resource_arn}` placeholders filled with real values |
| `Finding.evidence` (dict) | Pack logic | Medium-High — free-form dict, may contain any AWS API response fragment |
| `OwnerCandidate.team` | Inferred from tag pattern | High |
| `OwnerCandidate.contact` | Inferred | High |
| Reckoner query row values for `account`, `payer`, `account-name` groupings | DuckDB query output | High |

### 5.4 Fields Where Allowlist Would Break Analysis

- **`usage_type`**: AWS-defined vocabulary but includes region prefixes (e.g., `USE1-NatGateway-Bytes`). An overly strict allowlist would false-positive on legitimate AWS strings that happen not to be pre-registered. The vocabulary is unbounded on the AWS side (new usage types appear with new services).
- **`DeltaRow.name` for service grouping**: Service names are AWS vocabulary but new services appear. A stale allowlist would pseudonymize legitimate new service names.
- **`operation`**: Similar to `usage_type` — AWS-defined but unbounded and not pre-registered anywhere.

Recommendation: allowlist for services and usage types should be built from Cost Explorer `GetDimensionValues` responses cached from the scan itself, rather than a static compiled list.

---

## 6. Default-Change Blast Radius

### 6.1 Tests That Assert on Output Containing Identifier Values

| Test file | Line(s) | What it asserts |
|---|---|---|
| `tests/unit/test_full_report_snapshot.py` | 150 | `assert ACCOUNT_ID in html` — verifies `"000000000000"` appears in HTML output (uses `show_pii=True` for that test case specifically; but changing defaults would affect other assertions) |
| `tests/unit/test_full_report_snapshot.py` | 222 | Asserts `"account_id"` key exists in JSON output |
| `tests/unit/test_output_integrity.py` | 42 | Calls `_emit_output()` with `account_id="123456789012"` and `show_pii=True` |
| `tests/unit/test_investigate_ec2_cur.py` | 59 | `assert brief.top_accounts[0].name == "111111111111"` |
| `tests/unit/test_investigate_ec2_cur.py` | 260 | `assert "Top Contributing Accounts" in result.output` |
| `tests/unit/test_payer_binding.py` | 156, 160, 207, etc. | Assert exact `payer_account_id` values (`"999999999999"`, `"777777777777"`, `"555555555555"`) in workspace config |
| `tests/unit/test_findings_schema.py` | 69 | `assert f.account_id == "000000000000"` |
| `tests/unit/test_reckoner_contracts.py` | 162, 291 | Assert `redacted` flag on source manifests |

### 6.2 Docs, README Examples, or Docstrings with Sample Identifiers

| Location | Content |
|---|---|
| `redact.py` docstring examples | `'123456789012' -> 'XXXX-XXXX-9012'`; `'arn:aws:iam::123456789012:user/admin'` |
| `README.md` | Not audited at line level; likely contains sample commands but not output with identifiers |
| Sample report HTMLs in root (`kulshan-report-2026-*.html`) | Generated from real scans; **may contain real account IDs** depending on whether `--show-pii` was used |

### 6.3 Snapshot or Fixture Files Containing Real-Shaped Values

| File | Values | Source |
|---|---|---|
| `tests/fixtures/cost/anomaly_attribution_cases.json` | `000000000000`, `111111111111`, `222222222222` | Explicitly documented as synthetic placeholders (line 2 of file: `"_doc": "...Account IDs are placeholders only..."`) |
| `tests/fixtures/cost/aws_native_anomaly_cases.json` | Undetermined — not fully read | — |
| `tests/unit/test_denied_permissions.py:260-261` | `"123456789012"`, `"arn:aws:iam::123456789012:user/test"` | Test-constructed mock data |
| `tests/unit/test_payer_binding.py` | `"999999999999"`, `"777777777777"`, `"555555555555"` | Test-constructed synthetic data |

### 6.4 Test Guarding Against Real Account Leakage

`tests/unit/test_findings_schema.py:256-273` (`test_no_real_account_ids_in_fixture_file()`) — explicitly validates that the attribution fixture uses only placeholder account IDs (`000000000000`, `111111111111`, `222222222222`).

No equivalent guard exists for other fixture files or generated report files in the repo root.

---

## 7. Interaction with In-Flight Work

### 7.1 Reckoner Query Engine (v0.5.0 — just landed)

The Reckoner is the most recent major addition (commits `ba5d02d` through `770cad6`, the last ~20 commits on master). It introduces:

- **`reckoner/cost/semantics.py`**: Defines `GROUPINGS` mapping (`account`, `payer`, `account-name`, `service`, `region`, etc.) and `CUR_FIELDS` / `FOCUS_FIELDS` that surface customer-identifying columns directly.
- **`reckoner/query.py:execute_query()`**: Executes DuckDB SQL against the canonical relation and returns `QueryResult` with rows containing raw group values (including account IDs when grouped by `account` or `payer`).
- **`reckoner/renderers.py`**: 3 renderers (JSON, CSV, markdown) that output `QueryResult.rows` verbatim with no redaction hook.
- **`reckoner/terminal.py`**: Rich terminal renderer for QueryResult — also no redaction.
- **`reckoner/cli.py`**: User-facing commands (`query`, `save`, `explore`, `investigate`) that wire CLI to these renderers.

**Collision risk:** A redaction layer inserted into `_emit_output()` would NOT cover Reckoner output, because Reckoner has its own separate rendering pipeline. Any pseudonymization design must account for the Reckoner path independently.

**Independence assessment:** A redaction layer CAN proceed independently of the Reckoner work if it is designed as an output-format-agnostic transformation applied at the `QueryResult.rows` level before rendering. The `QueryResult` dataclass is frozen and returns row data as `tuple[dict, ...]`; a post-query, pre-render transformation point does not exist today and would need to be introduced.

### 7.2 Commitment Contracts (in Reckoner)

`reckoner/contracts.py` defines `SourceManifestRef` which already has a `redacted: bool` field (line observed in test assertions at `test_reckoner_contracts.py:146`). This indicates the Reckoner design anticipated a redaction need for S3 manifest URIs. The redaction is a simple boolean flag — it does not implement pseudonymization.

### 7.3 Cost Accounting Engine Overlap

The `reckoner/cost/semantics.py` module handles:
- Line item type classification (`CHARGE_CATEGORY_SQL`)
- Metric selection (formulas for unblended, amortized, net, effective cost)
- RI and SP accounting (commitment fee/unused/covered usage categorization)

These are purely numeric/categorical operations. They do not interact with identifier values except as grouping dimensions. A redaction layer applied after aggregation would not interfere with cost calculation correctness.

---

## 8. Unverified

| Item | Reason |
|---|---|
| `tests/fixtures/cost/aws_native_anomaly_cases.json` content | File not fully read; may contain additional identifier patterns |
| `reckoner/cache/` directory implementation | Directory exists but contains no `.py` files at this commit; cache behavior is undetermined |
| Sample HTML reports in repo root (`kulshan-report-2026-*.html`) | Multiple report files generated from what appear to be real scans; not inspected for presence of real account IDs |
| `checks/` pack implementations beyond `cost/__init__.py` | Only the cost pack was read in detail; other packs (security, sweep, dr, etc.) likely emit findings with `resource_arn` and `account_id` populated from live API responses, but the exact field construction was not traced per-pack |
| `real-cur/` directory content | Directory exists in repo root; may contain real CUR extracts with production identifiers |
| Whether `test_redact.py` existed before HEAD commit | `.pyc` cache files exist for it but no `.py` source; the HEAD commit message is "remove unimplemented placeholder stubs" — this test may have been deleted |
| Full content of `workspace/onboarding.py` logger calls | Lines 271, 386, 492 use `logger.info()` but only the surrounding context was read; exact interpolated values not confirmed for all three |
