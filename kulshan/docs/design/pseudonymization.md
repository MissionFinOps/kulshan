# Kulshan Pseudonymization Design

> **SUPERSEDED** by `docs/design/privacy-foundation-0.5.1.md` (2026-08-17).
> This document is retained for historical context only.

**Input:** `docs/audit/redaction-surface.md` at commit `770cad6a`
**Status:** Superseded. Historical reference only.

---

## 1. Pseudonym Scheme

### Format by identifier class

Each class produces a visually distinct pseudonym so an analyst reading a report can tell at a glance what kind of thing they are looking at.

| Identifier class | Pseudonym format | Example |
|---|---|---|
| AWS account ID (12-digit) | `acct-XXXX` where XXXX is a zero-padded sequential integer | `acct-0001` |
| Account name / alias | `org-XXXX` | `org-0003` |
| Resource ID (instance, volume, ENI, etc.) | `res-XXXX` | `res-0042` |
| ARN (full) | `arn:aws:{service}:{region}:acct-XXXX:{type}/res-YYYY` | `arn:aws:ec2:us-east-1:acct-0001:instance/res-0042` |
| Tag value | `tag-XXXX` | `tag-0007` |
| Owner / team / contact (inferred) | `team-XXXX` | `team-0002` |
| Savings Plan ARN | `sp-XXXX` | `sp-0001` |
| Reserved Instance ID | `ri-XXXX` | `ri-0003` |
| Email address | `user-XXXX@pseudo.invalid` | `user-0001@pseudo.invalid` |
| S3 bucket name | `bucket-XXXX` | `bucket-0005` |
| Hostname / endpoint | `host-XXXX.pseudo.internal` | `host-0012.pseudo.internal` |
| IP address | `10.0.XXXX.YYYY` (synthetic private range) | `10.0.0.12` |

ARN pseudonyms are composed: the service name and region pass through (they are AWS vocabulary), but the account portion and resource portion are replaced with their respective pseudonyms. This preserves structural readability while removing identifying content.

### Determinism scope

**Decision: pseudonyms are stable within a workspace, across invocations, indefinitely.**

Rationale: the primary analyst workflow is comparing two reports from the same AWS estate on different days. If account `acct-0001` means a different real account in Monday's report than in Friday's report, the comparison is useless. Per-invocation stability is insufficient for that workflow.

Stability is achieved through a persistent mapping file scoped to the workspace (see section 2). When no workspace is active (bare `kulshan report` without `-w`), the mapping is scoped to the default workspace directory.

### Collision handling

Sequential assignment guarantees zero collisions within a mapping file. Two different real values always receive different pseudonyms. The mapping is a bijection: each real value maps to exactly one pseudonym and vice versa.

If a mapping file from workspace A is applied to data from workspace B (a misconfiguration), previously unseen values receive new sequential assignments. Old assignments remain stable for values that happen to appear in both. This is acceptable because the mismatch is detectable (the mapping file records which payer it was created against).

### Derivation method

**Decision: sequentially assigned from a counter, not hash-derived.**

Rationale:
- Hash-based pseudonyms (e.g., HMAC-SHA256 truncated) produce opaque hex strings that are not human-readable and cannot be distinguished by class at a glance.
- Hash-based approaches require a secret key. If the key is lost, existing pseudonymized reports cannot be correlated with new ones. If the key is stored alongside the mapping, it adds no security over the mapping itself.
- Sequential assignment produces short, readable names. The mapping file IS the secret. Controlling the mapping file controls reversibility.

Implication: the mapping file is required to produce stable pseudonyms across invocations. If the mapping is absent, a fresh mapping is started (see section 2 for lifecycle).

---

## 2. Mapping Store

### Location and format

The mapping file lives inside the workspace data directory:

```
{workspace_dir}/pseudonym-map.toml
```

For the default workspace, this is under `platformdirs.user_data_dir("Kulshan", "missionfinops")`.

Format is TOML with sections per identifier class:

```toml
[metadata]
version = "1"
created_at = "2026-08-20T14:30:00Z"
payer_account_id_hash = "sha256:abcdef..."  # integrity check

[accounts]
"123456789012" = "acct-0001"
"987654321098" = "acct-0002"

[resources]
"i-0abc123def456" = "res-0001"
"vol-0fff999888" = "res-0002"

[tags]
"platform-team" = "tag-0001"
"payments-service" = "tag-0002"

[counters]
accounts = 2
resources = 2
tags = 2
```

### Lifecycle

- **Created** on first pseudonymized output if absent. A fresh counter starts at 1 for each class.
- **Appended** when new identifiers are encountered during a run. New assignments are written back atomically at the end of the invocation (not mid-stream, to avoid partial writes on crash).
- **Never deleted** by Kulshan automatically. The user can delete it manually to reset all pseudonyms.
- **Written by default.** Every pseudonymized output run updates the mapping. There is no "mapping-free" pseudonymization mode; without the mapping, stability across runs is not achievable.

### Keeping the mapping out of output paths

The mapping file is:
- Never included in any report output (HTML, JSON, SARIF, CSV, markdown, terminal).
- Never written to stdout.
- Never stored in the history SQLite database.
- Never transmitted via the MCP server.
- Located in a platform-specific data directory, not the working directory where reports are written. A user who shares their output directory (e.g., commits reports to git) does not inadvertently share the mapping.
- Excluded from `_atomic_write()` output paths by construction: output files go to user-specified paths or working directory; the mapping goes to workspace data directory.

### Reversal

**Decision: reversal is a supported operation.**

Interface: `kulshan pseudonym reveal <pseudonym-map.toml> <report-file>` reads a pseudonymized report and the mapping, and emits the report with real identifiers restored.

This is a local operation. It requires possession of both the mapping file and the report. The mapping file is the access control boundary. A client who receives a pseudonymized report cannot reverse it without being given the mapping.

### Absent, stale, or corrupt mapping

| Condition | Behaviour |
|---|---|
| Absent | A new mapping is created. All identifiers in this run get fresh sequential assignments starting at 1. |
| Stale (new identifiers not in map) | New assignments are appended. Existing assignments remain stable. |
| Corrupt (unparseable TOML, missing metadata section, counter mismatch) | Pseudonymization fails closed. No output is written. Error message names the corrupt file and suggests deletion to reset. |

---

## 3. Insertion Point

### There is no single choke point. There are six.

The audit (section 4.1) confirms no single function sits between all data and all output. The minimum coverage set is:

| # | Function | Module | Paths covered |
|---|---|---|---|
| 1 | `_emit_output()` | `cli.py:62` | HTML, JSON (file and stdout), SARIF, CSV, terminal report |
| 2 | `_render()` | `reckoner/cli.py:83` | Reckoner JSON, CSV, markdown, terminal |
| 3 | `export_brief()` | `analyze/export.py` | Analyze JSON, markdown, terminal |
| 4 | `_compact_finding()` + `_execute_preflight()` | `mcp_server/tools.py` | MCP tool JSON responses |
| 5 | `save_scan()` + `save_consolidated_scan()` | `history/__init__.py` | History SQLite persistence |
| 6 | Exception formatters | `workspace/payer_binding.py`, `workspace/sts.py` | Exception messages with account IDs |

### Substitution happens at render time, never in the data layer

This is confirmed to hold for all paths:

- `Finding` dataclass fields (`models.py:358-365`) carry real identifiers through aggregation, deduplication, fingerprinting, and scoring. Substitution occurs only when the finding is serialized for output.
- `DeltaRow.name` carries the raw GROUP BY value through the analysis pipeline. Substitution occurs in the export functions (`analyze/export.py`) when rendering to JSON, markdown, or terminal.
- Reckoner `QueryResult.rows` contain raw values from DuckDB. Substitution occurs in `_render()` before the renderer formats the string.
- `compute_fingerprint()` (`models.py:183`) continues to operate on real values. Fingerprints are internal identity, not output.

### Per-path insertion specification

**Path 1: `_emit_output()` (`cli.py:62`)**

A new function `pseudonymize_output(payload: Any, ctx: PseudonymContext) -> Any` is called inside `_emit_output()` before dispatching to any format renderer. It replaces the existing `redact_payload()` call site at `cli.py:106-141`. It applies to ALL formats including CSV (closing the audit gap where `findings_to_csv()` received raw findings) and JSON-to-stdout (closing the gap where stdout JSON was unredacted).

Terminal output is no longer exempt. The old "terminal is never redacted" policy (from `redact.py` docstring) is replaced by the uniform default-on pseudonymization. Terminal output receives the same pseudonymization as file output.

**Path 2: `_render()` (`reckoner/cli.py:83`)**

A call to `pseudonymize_query_result(result: QueryResult, ctx: PseudonymContext) -> QueryResult` is inserted before the renderer dispatch. This produces a new `QueryResult` with pseudonymized row values. Column metadata (names, types, units) is unchanged. The `QueryResult` dataclass is frozen, so a new instance is constructed.

Only grouping columns whose dimension is in the identifier set (`account`, `payer`, `account-name`, `resource`) are pseudonymized. Columns for `service`, `region`, `usage-type`, `operation`, `charge-category`, etc. pass through the allowlist.

**Path 3: `export_brief()` (`analyze/export.py`)**

A call to `pseudonymize_brief(brief, ctx: PseudonymContext)` is inserted at the top of `export_brief()` before format dispatch. This walks the brief dataclass and substitutes:
- `DeltaRow.name` when the originating dimension is `account_id`
- `OwnerCandidate.account_id`, `OwnerCandidate.team`, `OwnerCandidate.contact`
- `TagCoverage.*_values` lists
- Any 12-digit number pattern in `EvidenceItem.detail`

**Path 4: MCP (`mcp_server/tools.py`)**

`_compact_finding()` and `_execute_preflight()` are wrapped: before returning the JSON string, the payload is passed through `pseudonymize_output()`. The MCP worker process (`worker.py`) receives the context via an environment variable pointing to the workspace directory (from which the mapping file is loaded).

**Path 5: History SQLite (`history/__init__.py`)**

**Decision: history stores real values.**

Rationale: the history database enables cross-scan delta comparison (`get_previous_scan()` at `history/__init__.py`) using `account_id` as a lookup key. Pseudonymizing at rest would require the mapping file to be present and consistent for history queries to work. The history database is already in a restricted-permissions directory (`chmod 0o600` at line ~100) and is never exported or transmitted. It is local state, not output.

The `full_result_json` column (which stores the entire scan payload when `store_full_result=True`) is the one exception: this column is pseudonymized before storage, because it is functionally a report that happens to be stored in SQLite rather than written to a file. Lookup columns (`account_id`, `payer_account_id`, `session_account_id`) remain real.

**Path 6: Exception messages**

See section 4.

---

## 4. Logs and Exceptions

### Guarantee

No customer-identifying value (account ID, resource ID, ARN, tag value) reaches a log line at any level, an exception message string, or a formatted traceback.

### Mechanism

A wrapper type `SensitiveId` replaces raw `str` for all identifier values at the point they enter the codebase. Its `__str__()` and `__repr__()` methods return the pseudonym (or a fixed placeholder if no pseudonym context is available). Its `.raw` property returns the real value for internal computation.

This is not a convention. It is a type that makes the wrong thing (leaking the real value via string formatting) structurally impossible without explicit `.raw` access.

Specific application points:

| Entry point (from audit) | Change |
|---|---|
| `session.py:60` `get_account_id()` | Returns `SensitiveId` |
| `adapter.py:182` `adapt()` account_id assignment | Wraps in `SensitiveId` |
| `adapter.py:184` `adapt()` resource_arn assignment | Wraps in `SensitiveId` |
| `workspace/payer_binding.py:93` `extract_payer_from_cur()` | Returns `SensitiveId` |
| `workspace/config.py` config loading | Wraps `payer_account_id`, `expected_session_account_id` in `SensitiveId` |

Exception classes that currently interpolate raw values (`InvalidPayerEvidenceError`, `MultiplePayerEvidenceError`, `StsVerificationError`, `PayerBindingConflictError`) will receive `SensitiveId` instances. Their `__str__` automatically produces the pseudonym or placeholder, so the exception message never contains the real value even if the exception propagates unhandled.

Logger calls that might receive a `SensitiveId` (e.g., `consolidated.py:208` where `e` might contain one) format it via `__str__()` which produces the safe representation.

The `SensitiveId` type is simple:

```python
class SensitiveId:
    __slots__ = ("_raw", "_pseudo")

    def __init__(self, raw: str, pseudo: str | None = None):
        self._raw = raw
        self._pseudo = pseudo

    @property
    def raw(self) -> str:
        return self._raw

    def __str__(self) -> str:
        return self._pseudo or "[UNRESOLVED_ID]"

    def __repr__(self) -> str:
        return f"SensitiveId({self.__str__()!r})"

    def __eq__(self, other): ...
    def __hash__(self): ...
```

The `__eq__` and `__hash__` operate on `.raw` so that `SensitiveId` values work correctly as dict keys, set members, and deduplication keys without exposing the raw value through string conversion.

---

## 5. Allowlist

### Source

The vocabulary is compiled from:
1. The AWS Price List Bulk API service index (provides all current service codes, usage types, operations, and regions).
2. The existing `ChargeCategory` enum (`reckoner/cost/semantics.py:41-57`).
3. The existing `GROUPINGS` values (`reckoner/cost/semantics.py:673-689`).
4. AWS region list from the SDK endpoints file.
5. ISO 4217 currency codes.

This is a build-time step, not a runtime fetch.

### Storage format and location

```
src/kulshan/vocabulary/
    __init__.py
    v1.py          # version-stamped module
    services.txt   # one service code per line
    usage_types.txt
    operations.txt
    regions.txt
    currencies.txt
```

Each `.txt` file is a sorted, deduplicated, newline-delimited list. `v1.py` exposes them as frozen sets and declares the vocabulary version:

```python
VOCABULARY_VERSION = "2026.08.1"
SERVICES: frozenset[str] = _load("services.txt")
USAGE_TYPES: frozenset[str] = _load("usage_types.txt")
# ...
```

### Version stamping and update procedure

- The vocabulary version string (`YYYY.MM.N`) is included in every pseudonymized report output under a `pseudonymization.vocabulary_version` key.
- On each Kulshan release, a CI step regenerates the vocabulary files from current AWS data and bumps the `N` counter.
- The vocabulary is vendored. It does not change between releases. A given Kulshan version has exactly one auditable vocabulary.

### Reused constants from the codebase

| Existing constant | Location | Reuse |
|---|---|---|
| `ChargeCategory` enum | `reckoner/cost/semantics.py:41-57` | Values added to allowlist directly |
| `GROUPINGS` keys | `reckoner/cost/semantics.py:673-689` | Dimension names (not values) are structural, always pass through |
| `Severity` enum values | `models.py` | Pass through (already known safe) |
| `VALID_EFFORT`, `VALID_RISK` | `models.py` | Pass through |
| `TOOL_ORDER`, `TOOL_LABELS` | `orchestrator.py` | Pack names pass through |

### The hard case: tag values and `DeltaRow.name`

**Tag keys:** The five currently parsed tag keys (`owner`, `team`, `application`, `cost_center`, `environment`) are structurally known from `cur/schema.py:80-92`. The key names themselves are not pseudonymized; they are Kulshan's own semantic labels, not customer vocabulary. If future CUR parsing surfaces arbitrary tag key columns, the key name would be checked against the allowlist: standard AWS tag keys (`aws:createdBy`, etc.) pass through; customer-defined key names are pseudonymized.

**Tag values:** Always pseudonymized. There is no allowlist for tag values.

Rationale: a tag value like `prod` or `us-east-1` might look like AWS vocabulary, but in the tag value position it represents a customer's organizational decision. The string `prod` as a tag value means "this customer has an environment called prod." That is identifying in context even though the string itself is common. Treating all tag values as identifying is the conservative correct default.

**What this gets wrong:** A report that shows `tag-0001, tag-0002, tag-0003` for environment values is less immediately useful than one showing `prod, staging, dev`. The analyst loses the semantic meaning of the tag values. This is the intended tradeoff: safety over convenience. The `--show-identifiers` flag (section 7) restores real values when the analyst has confirmed the output will not leave their control.

**`DeltaRow.name`:** The semantic meaning of this field depends on which dimension produced it. The pseudonymization layer receives the dimension context alongside the value:

| Dimension | Treatment |
|---|---|
| `account_id`, `payer` | Pseudonymize (customer-identifying) |
| `service` | Check allowlist. Pass through if recognized; pseudonymize if not. |
| `region` | Check allowlist. Always passes (regions are bounded). |
| `usage_type` | Check allowlist. Pass through if recognized; pseudonymize if not. |
| `operation` | Check allowlist. Pass through if recognized; pseudonymize if not. |

**What this gets wrong in the other direction:** A new AWS service or usage type that shipped after the vendored vocabulary was frozen will be pseudonymized in reports until the next Kulshan release updates the vocabulary. The analyst sees `svc-0014` instead of `AmazonNewService`. This is acceptable because (a) it fails closed (unknown things are hidden rather than leaked), and (b) the next release fixes it automatically.

---

## 6. Failure Behaviour

### Rule: fail closed, per output path

If pseudonymization cannot classify a value or encounters an error, no output is written for that path. The process exits with a non-zero exit code and a message describing what failed.

### Per-path failure modes

| Path | Failure scenario | Behaviour |
|---|---|---|
| `_emit_output()` | Pseudonym context cannot be created (corrupt mapping, unwritable workspace dir) | Exit with `ExitCode.RUNTIME_ERROR`. No file written. No stdout output. Error printed to stderr. |
| `_emit_output()` | Unknown value type encountered during walk | Value is pseudonymized as `unknown-XXXX`. This is not a failure; it is the allowlist default. |
| Reckoner `_render()` | Same as above | Same: exit before rendering if context creation fails; unknown values get default pseudonyms. |
| `export_brief()` | Same | Same. |
| MCP `_compact_finding()` | Context creation fails (no workspace dir in worker environment) | Worker returns `{"status": "error", "payload": "pseudonymization unavailable"}`. ToolError is raised to the MCP client. |
| History `save_scan()` | Pseudonymization of `full_result_json` fails | The scan is saved without `full_result_json` (column set to NULL). A warning is logged. The scan summary (scores, severity counts) is still recorded since those contain no identifiers. |

### The no-silent-bypass guarantee

There is no code path where pseudonymization is "attempted but skipped on error." The two outcomes are:
1. Pseudonymized output is produced.
2. No output is produced and the user is told why.

The `--show-identifiers` flag is the only way to produce un-pseudonymized output, and it requires explicit opt-in (section 7).

---

## 7. Interface

### Flag name and direction

```
--show-identifiers
```

This replaces `--show-pii`. The old flag name is retained as a hidden deprecated alias that maps to the same behaviour, so existing CI scripts do not break immediately.

The name reads as opting out: the default is to hide identifiers. You are explicitly choosing to show them.

### Behaviour when opt-out is used

**Warning, not confirmation.** When `--show-identifiers` is passed:
- A single-line warning is printed to stderr: `warning: identifiers will not be pseudonymized in this output.`
- Output proceeds without pseudonymization.
- No interactive confirmation prompt. This is a CLI tool used in automation; interactive prompts break pipelines.

### Config file precedence

```
CLI flag > workspace config > default (pseudonymized)
```

Workspace `config.toml` may contain:

```toml
[output]
show_identifiers = true
```

This is for teams that have decided all output stays internal and pseudonymization is friction. The CLI flag overrides in either direction: `--show-identifiers` forces real values even if config says false; a future `--no-show-identifiers` forces pseudonymization even if config says true.

### Exempt subcommands

| Subcommand | Exempt? | Reason |
|---|---|---|
| `kulshan preflight` | Yes | Displays the caller's own identity to confirm connectivity. Pseudonymizing the account ID in a preflight check defeats its purpose. Already uses `mask_account_id()` for partial display (`capabilities.py:325`). Will show full ID to terminal, pseudonym to any structured output. |
| `kulshan workspace show` | Yes | Displays workspace configuration which the user wrote themselves. |
| `kulshan shell` (REPL) | No | Interactive REPL output is still output. Pseudonymized by default. |
| `kulshan history` | Partial | The history list shows pseudonymized account IDs. `kulshan history show <id> --show-identifiers` reveals real values. |
| All others | No | Default applies. |

---

## 8. Migration

### Disposition of `redact.py`

`redact.py` is deleted entirely. It is not extended, wrapped, or called by the new system.

Rationale:
- Its masking approach (last-4-digits) is incompatible with deterministic pseudonymization.
- It has zero test coverage at HEAD (deleted in commit `0599472e`).
- Its field classification sets (`_ACCOUNT_FIELDS`, `_TEXT_FIELDS`, etc.) are partially duplicated by the new vocabulary allowlist and `SensitiveId` type system.
- The `redact_payload()` deep-walk pattern is replaced by the pseudonymization context applied at the six insertion points.

### Is removal breaking?

Yes, for two audiences:

1. **Users of `--show-pii` flag.** The flag is retained as a deprecated alias for `--show-identifiers`. No breakage.
2. **Users who import `redact_payload` or other functions from `kulshan.redact` in external scripts.** This is an internal module not documented in public API. The `pyproject.toml` does not list it in any `[project.scripts]` or public interface. Acceptable breakage for a minor version bump.

The removal ships in the same release as the new pseudonymization system. There is no version where neither exists.

### Coexistence period

**Decision: zero coexistence.** Both layers never run simultaneously.

Rationale: running both would require defining precedence, interaction, and combined test coverage for a temporary state. The old module is untested and covers a subset of paths. Keeping it alive during migration adds risk without value. The new system is complete or it does not ship.

### Docs, README, docstrings, and fixtures

| Item (from audit section 6) | Disposition |
|---|---|
| `redact.py` docstring examples | Deleted with the file |
| `README.md` sample output | Updated to show pseudonymized examples |
| Sample report HTMLs in repo root | Regenerated with pseudonymization enabled, or deleted |
| Test fixtures with placeholder IDs (`000000000000`, etc.) | Retained. Fixtures use synthetic IDs that do not leak real data. Pseudonymization tests verify that these synthetic IDs ARE pseudonymized in output. |
| `test_full_report_snapshot.py:150` (`assert ACCOUNT_ID in html`) | Updated to assert the pseudonym appears instead |
| `_redact_payer()` in `workspace/payer_binding.py:167` | Deleted. Replaced by `SensitiveId.__str__()` |
| `mask_account_id()` in `capabilities.py:325` | Deleted. Replaced by `SensitiveId.__str__()` |

---

## 9. Test Strategy

### Required test set before merge, by output path

| Output path | Test | What it proves |
|---|---|---|
| JSON file export | `test_json_export_pseudonymized` | No raw 12-digit ID, no raw ARN, no raw tag value appears in output |
| HTML file export | `test_html_export_pseudonymized` | Same, plus pseudonym format is correct in rendered HTML |
| SARIF file export | `test_sarif_export_pseudonymized` | Account ID in tool properties, logical locations, and finding messages are all pseudonymized |
| CSV file export | `test_csv_export_pseudonymized` | `resource_id` column contains pseudonyms, not raw values |
| Terminal report | `test_terminal_report_pseudonymized` | Captured Rich output contains pseudonyms |
| Reckoner JSON | `test_reckoner_json_pseudonymized` | Row values for `account` grouping are pseudonymized; `service` values pass through |
| Reckoner CSV | `test_reckoner_csv_pseudonymized` | Same |
| Reckoner terminal | `test_reckoner_terminal_pseudonymized` | Same |
| Analyze JSON | `test_analyze_json_pseudonymized` | `DeltaRow.name` for account dimension, `OwnerCandidate.account_id`, tag values are pseudonymized |
| Analyze markdown | `test_analyze_markdown_pseudonymized` | Same |
| MCP tool response | `test_mcp_response_pseudonymized` | Compact findings and preflight response contain pseudonyms |
| History SQLite | `test_history_full_json_pseudonymized` | `full_result_json` column is pseudonymized; lookup columns are real |
| Exception messages | `test_exception_messages_no_raw_ids` | `str(StsVerificationError(...))` contains pseudonym, not raw value |
| Log output | `test_log_output_no_raw_ids` | Logger output captured at DEBUG level contains no 12-digit numbers matching real test IDs |

### Proving absence (not just presence of expected strings)

Each output-path test uses a two-step verification:

1. **Positive:** assert the expected pseudonym format appears.
2. **Negative:** assert the real test identifier does NOT appear anywhere in the output string. This is a raw substring search for the synthetic account ID used in the test fixture.

The negative assertion is the important one. It catches regressions where a new field is added to output without passing through pseudonymization.

### Property-based / fuzz coverage for unbounded free text

The `Finding.evidence` dict, `Finding.title`, `Finding.description`, and `Finding.recommended_action` fields contain interpolated identifiers in unpredictable positions. These are tested with:

- **Property test:** Generate random `Finding` dicts with synthetic 12-digit account IDs and ARN patterns injected at random positions in title, description, and evidence values. Assert that after pseudonymization, no generated ID appears in the serialized output. Use `hypothesis` with a custom strategy.
- **Boundary cases:** Empty strings, strings that are exactly 12 digits but not account IDs (e.g., timestamps in milliseconds), strings containing multiple account IDs, nested dicts in evidence.

### Test that fails if a new output path is added without pseudonymization

**Mechanism: an integration test that searches for raw identifiers across all output artifacts.**

`test_full_pipeline_no_leakage`:
1. Run a full `kulshan report --packs cost -o report.json` against mocked AWS responses containing a known synthetic account ID (`TEST_ACCOUNT = "111222333444"`).
2. Collect every artifact produced: the output file, stdout capture, stderr capture, history SQLite row, and any temp files in the output directory.
3. Assert `TEST_ACCOUNT` does not appear as a substring in any of them.

This test breaks whenever a new output path is introduced that emits identifiers without pseudonymization, regardless of which module produces it. It does not need to know the list of output paths; it checks the result.

A second variant does the same for the Reckoner pipeline (`kulshan query run ...`) and the analyze pipeline (`kulshan analyze cost ...`).

### Fixture policy

- Synthetic account IDs used in tests: `111222333444`, `555666777888`, `999000111222`. These are not valid AWS account IDs (AWS does not issue IDs starting with 1 or 5 in practice, though they are structurally valid 12-digit numbers).
- Fixture files document their synthetic nature in a `_doc` field (existing pattern from `anomaly_attribution_cases.json`).
- The existing `test_no_real_account_ids_in_fixture_file()` guard (`test_findings_schema.py:256`) is extended to cover all fixture files, not just the attribution fixture.
- No real account IDs, ARNs, or tag values from any production environment appear in test fixtures. This is enforced by a CI check that scans all `.json` and `.py` fixture files for 12-digit numbers not in the allowed synthetic set.

---

## 10. Sequencing

### Relationship to cost accounting engine work

The Reckoner landed in v0.5.0 (audit section 7.1). The pseudonymization layer operates at render time, after all aggregation. It does not interact with:
- Metric selection or formula evaluation
- Line item type classification
- RI/SP accounting or amortization
- DuckDB query execution

**Decision: pseudonymization ships independently and BEFORE any further Reckoner feature work.**

Rationale: the Reckoner already outputs raw account IDs through its rendering pipeline. Every Reckoner feature added before pseudonymization exists makes the problem worse. The pseudonymization insertion point in `reckoner/cli.py:_render()` must exist before new grouping dimensions or output formats are added to that pipeline.

### PR breakdown

| PR | Content | Gate |
|---|---|---|
| **PR 1: Vocabulary and SensitiveId** | `src/kulshan/vocabulary/` with vendored allowlists. `SensitiveId` type in a new `src/kulshan/pseudonym/types.py`. Unit tests for the type. No integration. | Merges when: type tests pass, vocabulary loads correctly, `__str__` never leaks `.raw`. |
| **PR 2: Mapping store** | `src/kulshan/pseudonym/mapping.py`. TOML read/write, atomic append, corruption detection. Unit tests. | Merges when: round-trip tests pass, corruption cases handled, concurrent-write safety verified. |
| **PR 3: Core pseudonymization engine** | `src/kulshan/pseudonym/engine.py`. The walk logic that classifies fields by identifier class, checks the allowlist, and applies substitutions. Operates on dicts/dataclasses. Property-based tests for free text scanning. | Merges when: property tests pass, allowlist boundary cases covered, no false negatives on known identifier patterns. |
| **PR 4: Insertion into report pipeline** | Wire `_emit_output()` in `cli.py` to use the engine. Cover HTML, JSON, SARIF, CSV, terminal. Delete `redact.py` and `redact_payload()`. Introduce `--show-identifiers` flag. Update all tests in `test_full_report_snapshot.py` and `test_output_integrity.py`. | Merges when: all 5 report-path tests pass, `test_full_pipeline_no_leakage` passes, old redact tests are replaced (not just deleted). |
| **PR 5: Insertion into Reckoner pipeline** | Wire `_render()` in `reckoner/cli.py`. Reckoner-specific tests. | Merges when: Reckoner output tests pass, allowlist correctly passes service/region values through. |
| **PR 6: Insertion into analyze and MCP pipelines** | Wire `export_brief()` and MCP tools. Analyze and MCP tests. | Merges when: all path tests pass. |
| **PR 7: SensitiveId at entry points + exception safety** | Wrap `get_account_id()`, adapter, workspace config, payer binding returns in `SensitiveId`. Update exception classes. Log safety test. | Merges when: exception message tests pass, log capture tests pass, no raw IDs in any logged output. |
| **PR 8: History pseudonymization** | Pseudonymize `full_result_json` before storage. History display uses pseudonyms for account display. | Merges when: history tests pass. |
| **PR 9: Reveal command** | `kulshan pseudonym reveal` implementation. | Merges when: round-trip test (pseudonymize then reveal) produces original output. |
| **PR 10: Default on** | Remove all `show_pii=True` defaults. Update README, CHANGELOG, docstrings. Extend fixture guard to all fixture files. Final integration test. | Merges when: `test_full_pipeline_no_leakage` passes for all three pipelines, README examples updated, no raw IDs in any generated sample report. |

### Which PR makes the default change

**PR 10.** Everything else builds toward it, but the default does not change until the full machinery is proven across all output paths.

### What must be true before PR 10 lands

1. All output-path tests from section 9 pass.
2. The `test_full_pipeline_no_leakage` integration test passes for report, Reckoner, and analyze pipelines.
3. Property-based tests for free text scanning pass with no failures over 10,000 examples.
4. The mapping store handles absent/stale/corrupt cases correctly.
5. `--show-identifiers` works for every path (escape hatch is functional).
6. The `reveal` command can round-trip any pseudonymized report back to real identifiers.
7. No raw 12-digit account ID appears in any test fixture, sample report, README example, or docstring in the repository (enforced by CI scan).

---

## Open Decisions

### 1. Terminal output exemption

The audit states terminal output was "explicitly never redacted" as an intentional design decision. This design removes that exemption: terminal output is pseudonymized by default, same as file output.

**Question:** Is removing the terminal exemption acceptable, or is there a workflow where seeing real account IDs in the terminal (but not in files) is required?

**Cost of keeping the exemption:** Terminal becomes the one path where a screen share, a screenshot, or a copied terminal session leaks real identifiers. It also means the "no path writes unredacted" guarantee has an asterisk. Every test must special-case terminal.

**Cost of removing the exemption:** Analysts running `kulshan report` interactively see pseudonyms in their own terminal, which adds friction when they know the account IDs and want to see them. Mitigated by `--show-identifiers`.

**Recommendation in this design:** Remove the exemption. But flagging because it reverses a prior intentional decision.

### 2. JSON to stdout without `-o`

The audit identifies a gap: JSON emitted to stdout (no `-o` flag) is currently not redacted. This design pseudonymizes it by default, same as all other paths.

**Question:** Is stdout JSON intended to be a "raw data pipe" for local tooling (jq, etc.) where pseudonymization is unwanted? Or should it be treated as output that might be redirected to a file or piped to another process?

**Cost of pseudonymizing stdout:** Users piping `kulshan report --format json` to `jq` for local analysis must pass `--show-identifiers` to get real values. Minor friction.

**Cost of not pseudonymizing stdout:** `kulshan report --format json > report.json` produces an unredacted file, bypassing all protection. The user may not realize the file is unredacted because they did not use `-o`.

**Recommendation in this design:** Pseudonymize stdout. The redirect-to-file risk outweighs the friction for pipe users.

### 3. Mapping file and multi-machine workflows

The mapping file is workspace-scoped and lives on the local filesystem. If an analyst runs Kulshan from two different machines against the same AWS estate (e.g., laptop and CI runner), each machine has its own mapping file and will assign different pseudonyms for the same real identifiers.

**Question:** Is cross-machine pseudonym stability required? If so, the mapping must be stored in a shared location (S3, git-tracked file, etc.) which introduces synchronization and access control complexity.

**Cost of requiring shared mapping:** Synchronization logic, merge conflicts, access control for a file that is effectively a decryption key.

**Cost of accepting per-machine divergence:** Reports from different machines cannot be trivially compared using pseudonyms alone. The `reveal` command restores real values, so comparison is possible but requires an extra step.

**Recommendation in this design:** Accept per-machine divergence. The mapping is local. Cross-machine comparison uses `reveal` to restore real values before comparing. This avoids introducing distributed state management into a local-first CLI.
