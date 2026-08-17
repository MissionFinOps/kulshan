# Unified Implementation Plan: Pseudonymization Engine + Consultant Export

> **SUPERSEDED** by `docs/design/privacy-foundation-0.5.1.md` (2026-08-17).
> This document is retained for historical context only.

**Status:** Superseded. Historical reference only.
**Inputs:**
- `docs/audit/redaction-surface.md` (commit `770cad6a`)
- `docs/design/pseudonymization.md` (prior Kiro session)
- Consultant export design (current session)
- Architectural review (ChatGPT corrections)

---

## Hard Decisions (settled)

These are not options. They are constraints the implementation must satisfy.

### 1. One PseudonymizationEngine

There is one engine, not a separate `ConsultantAnonymizer`. The engine accepts a policy object that controls strictness:

```python
class PseudonymPolicy:
    mode: Literal["normal", "consultant"]
    terminal_tty_bypass: bool   # True for normal mode when stdout is a TTY
    keep_tags: frozenset[str]   # Tag keys exempt from default pseudonymization
    block_unknown_columns: bool # True for consultant mode
```

The consultant exporter calls the same engine with `mode="consultant"`.

### 2. `redact.py` stays temporarily

`redact.py` remains in the codebase during migration. Each output path is migrated individually. Once all paths are covered by the new engine and tested, `redact.py` is deleted in a final cleanup PR. The two systems never run simultaneously on the same output path.

### 3. TTY vs structured output

| Context | Default behaviour |
|---|---|
| Interactive TTY terminal (stdout is a terminal) | Real identifiers shown |
| Structured stdout (piped, redirected, non-TTY) | Pseudonymized |
| File export (`-o`) | Pseudonymized |
| MCP tool responses | Pseudonymized |
| History SQLite `full_result_json` | Pseudonymized |
| Exception messages, log lines | Pseudonymized via `SensitiveId.__str__()` |
| `kulshan export consultant` | Always pseudonymized. No bypass flag accepted. |

Normal report output accepts `--show-identifiers` to force real values in any context. Consultant export does not.

### 4. HMAC-derived stable pseudonyms

Pseudonyms are generated via:

```
HMAC-SHA256(workspace_pseudonym_secret, identifier) -> truncated hex
```

Format per class:

| Class | Format | Example |
|---|---|---|
| Account ID | `acct_{hex6}` | `acct_7f31c2` |
| Resource ID | `res_{hex6}` | `res_a72f19` |
| ARN | `arn_{service}_{region}_acct_{hex6}_{type}_res_{hex6}` | `arn_ec2_us-east-1_acct_7f31c2_instance_res_a72f19` |
| Tag value | `tag_{hex6}` | `tag_e4c901` |
| Email | `user_{hex6}@pseudo.invalid` | `user_3a8bc1@pseudo.invalid` |
| S3 bucket | `bucket_{hex6}` | `bucket_f1a203` |
| Hostname | `host_{hex6}.pseudo.internal` | `host_d29e11.pseudo.internal` |
| SP ARN | `sp_{hex6}` | `sp_0f32a1` |
| RI ARN | `ri_{hex6}` | `ri_c83a4b` |
| Invoice | `inv_{hex6}` | `inv_42e1f7` |
| IP address | `10.pseudo.{octet3}.{octet4}` (derived from hash) | `10.pseudo.127.42` |

Properties:
- **Deterministic within a workspace.** Same identifier always produces the same pseudonym because the secret is stable.
- **No translation table required for determinism.** The HMAC computes the same output every time.
- **No discovery-order dependence.** Two runs produce identical pseudonyms regardless of row ordering.
- **Secret is a dedicated random 32-byte value** generated once per workspace and stored in `{workspace_dir}/pseudonym.key`. Not derived from account ID, payer ID, or workspace name.

An optional **customer-side mapping file** (`{workspace_dir}/pseudonym-labels.toml`) lets the customer annotate pseudonyms with friendly labels for their own use:

```toml
[labels]
"acct_7f31c2" = "Production-Payments"
"acct_a1b2c3" = "Staging"
```

This file is never included in any export. It is a local convenience.

### 5. Unknown CUR columns block consultant export

Every CUR column in the source must be classified before export:

| Classification | Action |
|---|---|
| `passthrough` | Copied as-is (cost, dates, pricing, product attributes, regions, service codes) |
| `pseudonymize` | Value replaced via HMAC pseudonym (accounts, resources, ARNs, invoices, SP/RI) |
| `transform_tag` | Tag value pseudonymized unless key is in `--keep-tag` set; retained values still scanned by validator |
| `redact` | Value replaced with fixed placeholder (rare; for fields like free-text descriptions that are not useful in billing analysis) |
| `UNKNOWN` | **Export blocked.** |

The column classification registry is a vendored file shipped with the package (`src/kulshan/pseudonym/cur_columns.toml`). It is version-stamped and updated on each release against the latest AWS CUR 2.0 documentation.

If a customer's CUR contains a column not in the registry (new AWS feature, custom columns), the export halts with:

```
EXPORT BLOCKED

1 unclassified column(s) found:
  - new_column_from_aws_update

Add classification to cur_columns.toml or update Kulshan.
```

Normal `kulshan report` does NOT block on unknown columns (it only reads its known subset). This invariant is consultant-export-specific.

### 6. `--keep-tag` does not bypass privacy validation

`--keep-tag environment` means: do not pseudonymize the value of that tag merely because it is a tag.

The retained value still passes through the final residual identifier scan (Gate 3). If a retained tag value contains an email, account ID, or other identifier pattern, the export is blocked.

```
EXPORT BLOCKED

Potential identifying data in retained tag:
  resource_tags_user_owner = "john.smith@bank.com"

Remove --keep-tag owner or scrub the tag value.
```

### 7. DuckDB-native CUR processing

CUR export uses DuckDB `COPY ... TO` with column-level transformation functions. Python never materializes the full dataset in memory.

Implementation approach:

```sql
COPY (
    SELECT
        billing_period,
        pseudo_account(line_item_usage_account_id) AS line_item_usage_account_id,
        pseudo_resource(line_item_resource_id) AS line_item_resource_id,
        line_item_unblended_cost,  -- passthrough
        product_region,            -- passthrough (allowlist)
        pseudo_tag(resource_tags_user_owner) AS resource_tags_user_owner,
        ...
    FROM cur_raw
    WHERE {scope_filters}
)
TO '{output_path}'
(FORMAT PARQUET);
```

DuckDB UDFs (`pseudo_account`, `pseudo_resource`, `pseudo_tag`) are registered as Python scalar functions that call the PseudonymizationEngine. DuckDB handles batching and memory management.

For CUR datasets too large for a single DuckDB pass (edge case: corrupt exports, memory-constrained systems), a chunked streaming fallback reads N rows at a time via `LIMIT/OFFSET` or partition iteration.

### 8. EvidenceScope replaces ConsultantExportFilter

A single immutable scope object governs both CUR and CE extraction:

```python
@dataclass(frozen=True)
class EvidenceScope:
    from_date: date
    to_date: date
    include_services: frozenset[str] | None = None  # None = all
    exclude_services: frozenset[str] | None = None
    include_accounts: frozenset[str] | None = None  # None = all
    exclude_accounts: frozenset[str] | None = None
    keep_tags: frozenset[str] = frozenset()
```

Both the CUR exporter and every CE API call compile their filters from this same object. This prevents scope mismatch where CUR shows accounts A+B but CE shows the entire payer.

Validation: exactly one of `include_*` / `exclude_*` may be set per dimension.

### 9. Three fail-closed gates before ZIP creation

```
GATE 1: Schema Classification
  Input columns:     132
  Classified:        132
  Unknown:           0
  PASS

GATE 2: Evidence Integrity
  Input rows:        4,813,225
  Output rows:       4,813,225
  Input total cost:  $8,431,221.37
  Output total cost: $8,431,221.37
  PASS

GATE 3: Residual Identifier Scan
  Raw account IDs:   0
  Email addresses:   0
  Raw ARNs:          0
  Access keys:       0
  Known resource ID patterns: 0
  PASS
```

All three must pass. Failure at any gate produces no ZIP. The user sees the failing gate, the specific issue, and what to do about it.

Gate 2 is critical: pseudonymization must never accidentally alter financial values. A SUM mismatch between input and output means a bug in the transformation layer.

### 10. CSV redaction gap fixed immediately

The existing bug (CSV export path in `_emit_output()` skips `redact_payload()`) is fixed as a standalone safety patch in the first PR. This is not part of the pseudonymization architecture; it is a bug fix using the existing `redact.py` until migration replaces it.

---

## Unified File Layout

```
src/kulshan/
├── pseudonym/                    # Core pseudonymization engine
│   ├── __init__.py
│   ├── engine.py                 # PseudonymizationEngine class
│   ├── policy.py                 # PseudonymPolicy dataclass
│   ├── types.py                  # SensitiveId type
│   ├── secret.py                 # Workspace secret generation/loading
│   ├── hmac_scheme.py            # HMAC derivation logic per identifier class
│   ├── classifier.py             # Field/column classification logic
│   ├── cur_columns.toml          # Vendored CUR column classification registry
│   └── vocabulary/               # Vendored allowlists
│       ├── __init__.py
│       ├── v1.py                 # Version-stamped vocabulary loader
│       ├── services.txt
│       ├── usage_types.txt
│       ├── operations.txt
│       ├── regions.txt
│       └── currencies.txt
│
├── export/                       # Consultant export feature
│   ├── __init__.py
│   ├── cli.py                    # Click commands: export consultant
│   ├── scope.py                  # EvidenceScope dataclass
│   ├── cur_exporter.py           # DuckDB-native full-schema CUR export
│   ├── ce_exporter.py            # Multi-dimension CE evidence export
│   ├── packager.py               # ZIP assembly + manifest + README
│   └── gates.py                  # Three-gate privacy validation
│
├── redact.py                     # TEMPORARY: stays during migration, deleted last
└── ...existing modules...
```

---

## Invariants (must be true at all times after merge)

1. **No output path writes raw identifiers unless the user is at an interactive TTY or has explicitly passed `--show-identifiers`.** Consultant export never accepts that flag.

2. **The same identifier always produces the same pseudonym within a workspace.** Guaranteed by HMAC + stable workspace secret.

3. **Consultant export never silently passes an unclassified CUR column.** Unknown column = blocked export.

4. **Pseudonymization never alters financial values.** Gate 2 enforces SUM equality between input and output.

5. **`--keep-tag` does not create a privacy bypass.** Retained tag values are scanned by Gate 3.

6. **CUR processing never materializes the full dataset in Python memory.** DuckDB handles projection and I/O.

7. **The pseudonym secret never appears in any output, export, log, or exception message.**

8. **`SensitiveId.__str__()` never returns the raw value.** This is the mechanism (not convention) preventing log/exception leakage.

9. **CUR and CE always use the same EvidenceScope.** There is no code path where they can diverge.

10. **If any gate fails, no ZIP is produced.** There is no override flag for consultant export gates.

---

## Test Matrix

### Per-output-path pseudonymization tests

| Output path | Test name | Proves |
|---|---|---|
| JSON file (`-o`) | `test_json_file_pseudonymized` | No raw 12-digit ID in output; pseudonym format correct |
| HTML file | `test_html_file_pseudonymized` | Same |
| SARIF file | `test_sarif_file_pseudonymized` | Same |
| CSV file | `test_csv_file_pseudonymized` | `resource_id` column contains pseudonyms |
| Terminal (non-TTY) | `test_terminal_nontty_pseudonymized` | Captured output contains pseudonyms |
| Terminal (TTY) | `test_terminal_tty_shows_real` | Real identifiers shown when TTY detected |
| JSON stdout (piped) | `test_json_stdout_pseudonymized` | Piped JSON does not contain raw IDs |
| Reckoner JSON | `test_reckoner_json_pseudonymized` | Account grouping values are pseudonymized |
| Reckoner CSV | `test_reckoner_csv_pseudonymized` | Same |
| Reckoner terminal | `test_reckoner_terminal_pseudonymized` | Same (non-TTY) |
| Analyze JSON | `test_analyze_json_pseudonymized` | DeltaRow.name for account, OwnerCandidate fields |
| Analyze markdown | `test_analyze_md_pseudonymized` | Same |
| MCP tool response | `test_mcp_pseudonymized` | Compact findings contain pseudonyms |
| History `full_result_json` | `test_history_json_pseudonymized` | Stored JSON is pseudonymized; lookup columns are real |
| Exception messages | `test_exceptions_no_raw_ids` | `str(error)` contains pseudonym, not raw value |
| Log output | `test_logs_no_raw_ids` | DEBUG-level capture has no raw 12-digit IDs |

### Consultant export gate tests

| Test | Proves |
|---|---|
| `test_gate1_blocks_unknown_column` | Adding an unclassified column to fixture CUR blocks export |
| `test_gate1_passes_all_classified` | All columns classified = pass |
| `test_gate2_detects_sum_mismatch` | Injecting a transformation bug that alters cost = blocked |
| `test_gate2_passes_correct_totals` | Correct transformation preserves totals |
| `test_gate3_detects_residual_account_id` | Leaving a raw 12-digit ID in output = blocked |
| `test_gate3_detects_residual_email` | Same for email |
| `test_gate3_passes_clean_output` | Fully pseudonymized output passes |
| `test_keep_tag_still_scanned` | `--keep-tag owner` with email value = blocked by Gate 3 |

### Absence tests (proving no leakage)

| Test | Mechanism |
|---|---|
| `test_full_pipeline_no_leakage` | Run full report with synthetic ID `111222333444`; assert it does not appear as substring in any output artifact |
| `test_reckoner_pipeline_no_leakage` | Same for Reckoner |
| `test_analyze_pipeline_no_leakage` | Same for analyze |
| `test_consultant_export_no_leakage` | Same for consultant ZIP contents |

### Property-based tests

| Test | Coverage |
|---|---|
| `test_freetext_pseudonymization_property` | Hypothesis: generate random findings with embedded 12-digit IDs in title/description/evidence; assert none survive pseudonymization |
| `test_hmac_determinism_property` | Hypothesis: same (secret, identifier) always produces same pseudonym |
| `test_hmac_no_collision_property` | Hypothesis: distinct identifiers produce distinct pseudonyms (within practical hex space) |

### Structural guard test

| Test | Mechanism |
|---|---|
| `test_new_output_path_requires_pseudonymization` | Integration test that searches ALL produced artifacts for a known synthetic ID; breaks if a new unprotected path is added |
| `test_cur_columns_registry_covers_known_schema` | Parses AWS CUR 2.0 documentation columns (vendored list) and asserts every one has a classification in `cur_columns.toml` |

### Fixture policy

- Synthetic account IDs in tests: `111222333444`, `555666777888`, `999000111222`
- CI check scans all fixture files for 12-digit numbers not in the allowed synthetic set
- No real account IDs, ARNs, or tag values from production in any test fixture

---

## Implementation Sequence

### Phase 0: Safety patch (standalone, immediate)

| PR | Content | Gate |
|---|---|---|
| **PR 0** | Fix CSV redaction gap in `_emit_output()`: apply `redact_payload()` to findings before `findings_to_csv()` unless `show_pii=True`. Three-line change. | Tests pass; CSV output no longer contains raw account IDs. |

### Phase 1: Pseudonymization foundation

| PR | Content | Gate |
|---|---|---|
| **PR 1** | `src/kulshan/pseudonym/types.py`: `SensitiveId` type. `src/kulshan/pseudonym/secret.py`: workspace secret generation/loading. Unit tests for both. | `SensitiveId.__str__()` never returns raw. Secret generation produces 32 random bytes. Round-trip load/store works. |
| **PR 2** | `src/kulshan/pseudonym/hmac_scheme.py`: HMAC derivation per identifier class. `src/kulshan/pseudonym/vocabulary/`: vendored allowlists. Unit tests. | Determinism test passes. Format per class matches spec. Allowlist loads correctly. |
| **PR 3** | `src/kulshan/pseudonym/engine.py` + `policy.py` + `classifier.py`: Core engine with dict/dataclass walk, field classification, allowlist lookup, substitution. Property-based tests for free text. | Property tests pass over 10,000 examples. Known identifier patterns never survive. |

### Phase 2: Output path migration (one path per PR)

| PR | Content | Gate |
|---|---|---|
| **PR 4** | Wire engine into `_emit_output()` for JSON/HTML/SARIF/CSV file exports. Introduce `--show-identifiers` flag (hidden alias `--show-pii`). TTY detection for terminal. | All report-path tests pass. `test_full_pipeline_no_leakage` passes. |
| **PR 5** | Wire engine into Reckoner `_render()`. | Reckoner output tests pass. Service/region values pass through allowlist correctly. |
| **PR 6** | Wire engine into `export_brief()` (analyze) and MCP `_compact_finding()` / `_execute_preflight()`. | Analyze and MCP tests pass. |
| **PR 7** | Wrap entry points with `SensitiveId`: `get_account_id()`, adapter, workspace config, payer binding. Update exception classes. | Exception message tests pass. Log capture tests pass. |
| **PR 8** | Pseudonymize `full_result_json` in history SQLite before storage. Lookup columns stay real. | History tests pass. |

### Phase 3: Consultant export feature

| PR | Content | Gate |
|---|---|---|
| **PR 9** | `src/kulshan/pseudonym/cur_columns.toml`: vendored CUR column classification registry. `src/kulshan/export/scope.py`: `EvidenceScope` dataclass. `src/kulshan/export/gates.py`: three-gate validation. Unit tests. | Gate tests pass. Unknown column blocks. Sum integrity verified. Residual scan catches patterns. |
| **PR 10** | `src/kulshan/export/cur_exporter.py`: DuckDB-native full-schema CUR export with UDF-based pseudonymization. | CUR export produces correct Parquet. No memory blowup on large fixtures. All columns classified. Gate 2 sum matches. |
| **PR 11** | `src/kulshan/export/ce_exporter.py`: Multi-dimension CE evidence export using EvidenceScope. Account pseudonyms match CUR pseudonyms. | CE datasets use same pseudonyms as CUR for accounts. Scope filtering confirmed via mocked API. |
| **PR 12** | `src/kulshan/export/packager.py` + `src/kulshan/export/cli.py`: ZIP assembly, manifest, auto-README, Click CLI (`kulshan export consultant`). Interactive mode (prompt_toolkit) and non-interactive mode. | End-to-end: synthetic CUR + mocked CE produces valid ZIP. All three gates pass. `test_consultant_export_no_leakage` passes. |

### Phase 4: Cleanup

| PR | Content | Gate |
|---|---|---|
| **PR 13** | Delete `redact.py`. Remove `redact_payload()`, `redact_account_id()` imports. Remove `_redact_payer()` from payer_binding. Remove `mask_account_id()` from capabilities. Update docstrings, README examples. | All tests pass without `redact.py`. No import errors. |
| **PR 14** | `kulshan pseudonym reveal` command: reads a pseudonymized report + the workspace secret, restores real identifiers. | Round-trip test: pseudonymize then reveal = original values. |

---

## What survives from each prior design

### From pseudonymization.md (prior Kiro)

| Component | Survives? | Notes |
|---|---|---|
| `SensitiveId` type | **Yes** | Unchanged. Core mechanism for log/exception safety. |
| Vocabulary allowlist (vendored, version-stamped) | **Yes** | Unchanged. Shipped with package, not fetched at runtime. |
| Workspace-scoped stability | **Yes** | Achieved via HMAC + secret instead of sequential counter + mapping. |
| Sequential counter pseudonyms (`acct-0001`) | **No** | Replaced by HMAC-derived hex (`acct_7f31c2`). |
| TOML mapping store (`pseudonym-map.toml`) | **No** | Not needed for determinism. Replaced by `pseudonym.key` (the secret) + optional `pseudonym-labels.toml` (customer annotations). |
| 6 insertion points | **Yes** | Same set: `_emit_output`, `_render`, `export_brief`, MCP tools, history, exceptions. |
| `redact.py` immediate deletion | **No** | Stays during migration. Deleted in PR 13 after all paths migrated. |
| `--show-identifiers` flag | **Yes** | Unchanged. |
| Terminal exemption removed | **Partially** | TTY terminal shows real IDs by default (normal mode). Non-TTY/structured output is pseudonymized. Consultant export is always pseudonymized. |
| `kulshan pseudonym reveal` command | **Yes** | Moved to Phase 4 (PR 14). |
| 10-PR sequence | **Restructured** | Merged with export PRs into unified 14-PR sequence. |
| Fail-closed behaviour | **Yes** | Strengthened with explicit three-gate system for consultant export. |
| Property-based free text tests | **Yes** | Unchanged. |

### From consultant export plan (this session)

| Component | Survives? | Notes |
|---|---|---|
| `kulshan export consultant` command | **Yes** | First-class Click group + subcommand. |
| Full-schema CUR export (`SELECT *`) | **Yes** | Via DuckDB COPY with UDF pseudonymization. |
| Multi-dimension CE evidence export | **Yes** | Unchanged. |
| ZIP package structure (manifest, README, Parquet, privacy report) | **Yes** | Unchanged. |
| `ConsultantAnonymizer` class | **No** | Replaced by `PseudonymizationEngine` with consultant policy. |
| `ConsultantExportFilter` | **No** | Renamed to `EvidenceScope` (immutable, shared by CUR and CE). |
| `anonymize/column_rules.py` | **Absorbed** | Becomes `pseudonym/cur_columns.toml` (same concept, vendored registry). |
| `anonymize/validator.py` | **Absorbed** | Becomes `export/gates.py` with three gates instead of one. |
| Translation table persistence | **No** | HMAC determinism removes the need. Optional labels file replaces it. |
| Interactive CLI with service/account selection | **Yes** | Unchanged. |
| `--keep-tag` option | **Yes** | With the constraint that retained values are still scanned by Gate 3. |
| Privacy audit (regex scan before ZIP) | **Yes** | Becomes Gate 3 of the three-gate system. |

### From ChatGPT review (new requirements)

| Requirement | Incorporated as |
|---|---|
| One engine, not separate anonymizer | Decision 1. Consultant export consumes engine with strict policy. |
| HMAC-derived pseudonyms | Decision 4. `acct_{hex6}` format. |
| Unknown columns block export | Decision 5. Gate 1. |
| `--keep-tag` still scanned | Decision 6. Gate 3 enforcement. |
| DuckDB-native processing | Decision 7. UDF + COPY. |
| EvidenceScope | Decision 8. Immutable shared scope. |
| Three gates | Decision 9. Schema + integrity + residual. |
| `redact.py` temporary retention | Decision 2. Deleted in PR 13. |
| TTY shows real, structured pseudonymizes | Decision 3. |

---

## Components explicitly removed (no longer built)

| Removed | Reason |
|---|---|
| `src/kulshan/anonymize/` directory | Merged into `src/kulshan/pseudonym/`. One engine. |
| `ConsultantAnonymizer` class | Replaced by engine + policy. |
| `pseudonym-map.toml` (sequential mapping store) | HMAC removes need for persistent mapping. |
| Discovery-order counters (`acct_01, acct_02`) | HMAC-derived aliases are order-independent. |
| Separate `ConsultantExportFilter` | `EvidenceScope` serves both CUR and CE. |
| Immediate `redact.py` deletion | Deferred to Phase 4 cleanup. |
| `test_redact.py` restoration | Old tests encode masking behaviour being abandoned. New tests cover pseudonymization. |

---

## Open items (zero, all decided)

All three questions from the prior design are resolved in Decision 3 above:
- Terminal exemption: TTY shows real, non-TTY pseudonymizes.
- JSON stdout: pseudonymized by default (non-TTY).
- Multi-machine mapping: not guaranteed in v1. Stable within one workspace (same secret = same pseudonyms).

---

## Estimated effort

| Phase | PRs | Effort |
|---|---|---|
| Phase 0 (safety patch) | 1 | 1 hour |
| Phase 1 (foundation) | 3 | 12-16 hours |
| Phase 2 (migration) | 5 | 16-20 hours |
| Phase 3 (consultant export) | 4 | 20-25 hours |
| Phase 4 (cleanup) | 2 | 4-6 hours |
| **Total** | **15 PRs** | **~55-70 hours** |

Each PR has a defined stopping gate. No PR depends on a later PR. The sequence can be paused at any phase boundary and still deliver value (Phase 0 fixes a bug; Phase 1+2 gives always-on pseudonymization; Phase 3 adds consultant export; Phase 4 removes legacy code).
