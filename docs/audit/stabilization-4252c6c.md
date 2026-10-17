# Kulshan stabilization: 4252c6c

Branch: `fix/p0-p3-stabilization`.
Starting commit: `4252c6ca76be8e6fd186dc61915c8799653d50ff`.
Ending implementation commit: `e1d1ade` (the subsequent audit-only commit records this ledger).
Previous stabilization tip: `ffd7b70`. The independent audit invalidated four earlier completion claims; the targeted repair and new evidence are recorded below.
Implementation commits: `12e4409`, `a57ab49`, `21dfa99`, `4a3650a`, `7c463d8`, `e1d1ade`.

All validation used offline mocks, fixtures or local package artifacts. No live AWS calls, pushes, merges, releases, tags, deployments or publishing. The three protected untracked user files were never modified or staged.

## Finding results

Paths in this table are relative to `kulshan/`; the complete exact changed-file inventory follows.

| Finding | Status | Implementation and regression evidence |
|---|---|---|
| P0-01 | PASS | `src/kulshan/checks/cost/cost_fetcher.py`, `checks/cost/__init__.py`: injected session is authoritative for CE and Organizations; standalone profiles retained. `test_stabilization.py`: direct/profile sessions, constructor fallback rejection, missing credentials, pack forwarding, and mocked cross-account AssumeRole through create_session. Adjacent cost paths inspected: no other client/session constructors bypass it. Existing workspace execution tests cover connection/account selection. |
| P1-01 | PASS | `pyproject.toml`: MCP >=1.0,<2 in mcp/dev extras. Installed 1.30.0. `test_mcp_execution.py` only skips when top-level optional mcp is absent; incompatible installed SDK fails import. `.github/workflows/ci.yml` adds explicit extra job. `test_mcp_privacy.py` tests registration and real local stdio initialization/list_tools. |
| P1-02 | PASS | `mcp_server/tools.py` reuses orchestrator summary for report/quick security: complete/partial/unavailable, retains partial findings and missing-permission coverage. Success, zero findings, denied/skipped, partial scans tested in `test_mcp_privacy.py`. |
| P1-03 | PASS | Revalidated by the scoped field-semantics repair e1d1ade after the audit of 0b4d520 found cross-field enum/currency corruption. Explicit identifier fields retain deterministic aliases; authoritative severity/currency/status/confidence/region metadata bypasses learned-name substitution. Known distinctive names can be protected in prose; ambiguous common tokens withhold that prose. test_mcp_field_semantics.py exercises all ten required collisions through returned MCP JSON, simultaneous confidentiality/schema/financial integrity, nested identifiers, determinism, different secrets and fail-closed failures. Earlier package/tool-discovery evidence is historical; current source-only checks are recorded below. |
| P1-04 | PASS | Revalidated after the independent audit withdrew the earlier PASS. Consolidation retains errors, denied/skipped coverage, source connections, per-source metadata and regional coverage. Canonical completeness drives consolidated status, CLI exits and report coverage; incomplete scores are withheld. CUR-only failures no longer hardcode partial=False. `test_merge_blockers.py` exercises five combinations through consolidation and actual CLI JSON, a failed connection, CUR-only CLI failure, and JSON/HTML/terminal score presentation. |
| P1-05 | PASS | Revalidated after the independent audit withdrew the earlier PASS. DROP names are internal only: package manifests/privacy reports/README and schema gate metadata expose ordinal removed-column labels and counts, not original names. `test_actual_zip_omits_dropped_column_names` creates a consultant ZIP with cost_category_project_nightingale, inspects all text and Parquet schemas, checks the native numeric value and verifies all three gates pass. Existing export integrity suites pass. |
| P2-01 | PASS | `reckoner/query.py`, `contracts.py`, `registries.py`: calendar-current UTC month, separate latest-available month, explicit half-open custom ranges. Historical December/January fixture distinguishes current October from latest January. `test_stabilization_finance.py`; updated stable vocabulary regression. |
| P2-02 | PASS | Shared `reckoner/cost/semantics.py:validate_currencies` used by high-level executor. Missing currency rejected, mixed currency requires grouping, totals remain separate by currency. Lower-level mixed-currency total is None. `test_stabilization_finance.py` and existing canonical-cost suite. |
| P2-03 | PASS | Independent aggregate before LIMIT with same range/filters/exclusions. Currency-grouped totals and terminal presentation retained. `test_stabilization_finance.py` verifies visible-row count and full total. |
| P2-04 | PASS | `billing_integrity.py`: ended month means unknown finality, never calendar-derived trust. Validates period month; CE/CUR corroboration is not independent verification. `test_billing_integrity.py`, `test_stabilization.py`. No invoice-reconciliation workflow added. |
| P2-05 | PASS | Revalidated after the independent audit withdrew the earlier PASS. Executive eligibility requires finite measured coverage/utilization/waste scores plus purchase mix, velocity, concentration, positive spend and findings count. Empty/missing/partial/unavailable evidence yields composite_score=None, composite_grade=N/A and empty pillars; valid evidence preserves the existing scoring calculation. `test_executive_scoring_eligibility` covers all five cases. The original all-empty 72/C result is no longer possible. |
| P2-06 | PASS | `csv_safety.py` shared by findings, Reckoner and legacy cost CSV writers. Formula prefixes and leading whitespace protected; signed numeric strings and numerical values unchanged. `test_stabilization.py`, existing CSV/privacy suites. |
| P2-07 | PASS | `redact.py`, `pseudonym/{classifier,engine}.py`: unknown strings/map keys scan supported identifiers, IPv6, accountless ARNs, temporary keys; labeled secrets protected without matching every 40-character hash. Strong required CLI/investigation/query privacy cannot silently fall back. `test_stabilization.py`, pseudonym/privacy suites. |
| P3-01 | PASS | Core CI matrix added: Python 3.9/3.11/3.13; MCP job Python 3.12. Locally executed 3.12.10; 245 source files parse under 3.9?3.13 grammar. Remote matrix execution is pending; static parsing is not runtime proof. MCP optional extra is not claimed for Python 3.9. |
| P3-02 | PASS | Measured baseline 2318 Ruff violations; latest repair 2313. Fatal rules pass. `tools/check_ruff_baseline.py` rejects increases per file/rule using `tools/ruff-baseline.json`; CI runs both. Focused strict mypy covers CSV protection, alias batching, billing integrity and query execution. Imports skipped; no whole-repository typing claim. |
| P3-03 | PASS | Source search found no runtime use/import of Jinja2 or PyJWT: removed direct requirements. MCP can install PyJWT transitively. Retained awscrt for botocore credential/login support. Local extra install, fresh wheel dependency resolution and pip check pass. |
| P3-04 | PASS | `export/batching.py` streams distinct values in 2048-element Python batches, reused separately by export and independent integrity derivation. 10,000-distinct-value synthetic test uses batch size 127. Existing EXCEPT ALL row-equivalence gates remain. No time/throughput or bounded-total-memory claim. |
| P3-05 | PASS | Updated architecture, MCP, Reckoner cost semantics and redaction-surface audit documents with implemented contracts and limits. Historical audit conclusions are superseded by this ledger. |
| P3-06 | PASS | Wheel/sdist build, isolated fresh install, pip check, version/help, installed-wheel tool discovery, and wheel/source comparison pass. Existing IAM policy/registry/hash/action inventory, consent-first update and pseudonym-secret trust tests run. Windows POSIX permission test is explicitly SKIPPED, not PASS. No permission or network-behavior additions. |

Local diagnostic logs are retained under ignored `.audit-tmp/stabilization-evidence/` (not committed).

## Actual validation commands and outcomes

Commands ran from repository root unless indicated. Interpreter `P` below is exactly `.venv/Scripts/python.exe`. Tests used `-c kulshan/pyproject.toml` to avoid the root coverage configuration. Normal temporary-file and local subprocess-pipe access required elevated execution because the sandbox denied Windows fixture/pipe access. These permissions did not authorize or perform live AWS validation.

- Baseline: `P -m pytest kulshan/tests -q --disable-warnings --tb=short > baseline-stabilization.log 2>&1`: stalled with no output, interrupted, exit 1; inconclusive, not PASS. User-provided prior 599-test result was not represented as a newly executed baseline.
- Baseline Ruff: `P -m ruff check kulshan/src kulshan/tests --output-format json`: exit 1, 2318 findings. Final configured Ruff also exits 1 due to historical debt, 2314 findings. Regression gate exits 0.
- Initial new regression run: `P -m pytest -c kulshan/pyproject.toml kulshan/tests/unit/test_stabilization.py --tb=short`: 19 failed, 5 passed (expected red, exit 1).
- Initial financial fixture attempt: five setup errors from sandbox temporary-file restrictions (exit 1), not a financial PASS. Subsequent normal-permission run: 139 passed, 1 failed due to new period missing in contract registry. Fixed contract registration.
- Subsequent export batch run: 91 passed, 2 failed because transport test wrappers lacked cursor support. Wrappers updated to expose real DuckDB cursors; no production fallback to fetchall introduced.
- Pass 1: `P -m pytest -c kulshan/pyproject.toml kulshan/tests/unit/test_mcp_execution.py kulshan/tests/unit/test_mcp_privacy.py kulshan/tests/unit/test_stabilization.py -k 'not prior_month and not customer_text and not residual_ipv6' --tb=short`: exit 0, 41 passed, 4 deselected, no skips.
- Pass 2: `P -m pytest -c kulshan/pyproject.toml kulshan/tests/unit/test_stabilization.py kulshan/tests/unit/test_stabilization_finance.py kulshan/tests/unit/test_stabilization_scale.py kulshan/tests/unit/test_consultant_export.py kulshan/tests/unit/test_privacy_output.py kulshan/tests/unit/test_reckoner_query.py kulshan/tests/unit/test_billing_integrity.py --tb=short`: exit 0, 153 passed, no skips.
- Focused milestone: `P -m pytest -c kulshan/pyproject.toml kulshan/tests/unit/test_stabilization.py kulshan/tests/unit/test_stabilization_finance.py kulshan/tests/unit/test_stabilization_scale.py kulshan/tests/unit/test_mcp_execution.py kulshan/tests/unit/test_mcp_privacy.py --tb=short`: exit 0, 61 passed (before final added regressions).
- First final full run: 660 passed, 1 failed (hard-coded period vocabulary), 1 skipped. Updated expected vocabulary. Second run: 661 passed, 1 skipped. Added incomplete-pack score/render regression; next run: 662 passed, 1 skipped. Final cross-account/category-header correction: command below, 663 passed, 1 skipped. Full repeats followed meaningful changes/findings, not cosmetic cleanup.
- **Previous stabilization full suite (superseded by the repair validation below):** `P -m pytest -c kulshan/pyproject.toml kulshan/tests --disable-warnings --tb=short -rs > final-stabilization-tests.log 2>&1`: exit 0, **663 passed, 1 skipped**, 16.53 seconds. Skip: `test_pseudonym_secret.py:47`, POSIX permissions not enforced on Windows. This check remains unverified locally; Linux CI is configured to exercise it.
- Final focused trust/P0/P1/finance/privacy: `P -m pytest -c kulshan/pyproject.toml kulshan/tests/unit/test_stabilization.py kulshan/tests/unit/test_stabilization_finance.py kulshan/tests/unit/test_stabilization_scale.py kulshan/tests/unit/test_mcp_execution.py kulshan/tests/unit/test_mcp_privacy.py kulshan/tests/unit/test_iam_gate_a.py kulshan/tests/unit/test_iam_gate_b.py kulshan/tests/unit/test_iam_composition.py kulshan/tests/unit/test_trust_integrity.py kulshan/tests/unit/test_update_check.py kulshan/tests/unit/test_pseudonym_secret.py -rs --tb=short`: exit 0, 170 passed, 1 POSIX skip (before final category-header/cross-account change; both covered in final full run).
- Additional incomplete-report gate: `P -m pytest -c kulshan/pyproject.toml kulshan/tests/unit/test_stabilization.py kulshan/tests/unit/test_output_integrity.py kulshan/tests/unit/test_cli_integration.py kulshan/tests/unit/test_workspace_execution.py --tb=short`: exit 0, 75 passed, no skips.
- MCP install: `P -m pip install -e "./kulshan[mcp]" "mcp>=1.0,<2"`: exit 0, installed SDK 1.30.0 replacing incompatible SDK 2.0.0. Initial sandbox install failed with temporary-directory denial; normal-permission install succeeded.
- Final MCP runtime: `P -m pytest -c kulshan/pyproject.toml kulshan/tests/unit/test_mcp_execution.py kulshan/tests/unit/test_mcp_privacy.py --tb=short`: exit 0, 22 passed, no skips. Stdio initialize/list_tools succeeds with seven tools; no tool invokes AWS. One sandbox subprocess attempt failed with WinError 5; normal-permission rerun passed.
- `P -m ruff check --select E9,F63,F7,F82 kulshan/src kulshan/tests`: exit 0. `P kulshan/tools/check_ruff_baseline.py`: exit 0, residual 2314 vs 2318 baseline. Baseline is narrowly documented historical debt, not a clean full-lint claim.
- From `kulshan/`: `../.venv/Scripts/python.exe -m mypy --config-file mypy-stabilization.ini`: exit 0, strict checks pass in 4 files. One earlier invocation from the wrong working directory failed to locate the interpreter; corrected command passed.
- Python static compatibility: `ast.parse(..., feature_version=(3, minor))` for all 245 source files, minor 9?13: zero syntax errors. `py -0p` lists only local 3.12 and 3.14. CI representative runtime versions configured but not run here.
- From `kulshan/`: `../.venv/Scripts/python.exe -m build`: exit 0; `dist/kulshan-0.6.2.tar.gz` and `dist/kulshan-0.6.2-py3-none-any.whl` built using isolated build environments. Rebuilt after final source changes.
- `P -m venv .audit-venv/stabilization-wheel`; `.audit-venv/stabilization-wheel/Scripts/python.exe -m pip install "./kulshan/dist/kulshan-0.6.2-py3-none-any.whl[mcp]"`: exit 0, resolved dependencies into fresh environment. Final rebuilt wheel installed with `--no-deps --force-reinstall`.
- Fresh-wheel `python -m pip check`: exit 0, no broken requirements; `kulshan.exe --version`: exit 0, 0.6.2; `kulshan.exe --help`: exit 0. Installed-wheel FastMCP discovery: seven tools, import path points into isolated site-packages. Wheel/source check: zero Python-source mismatches; IAM policy, registry and hash are included.

## Financial/privacy verification and remaining limits

Existing native numeric and multiset row-integrity tests pass. No currency conversion was introduced. Amounts retain native values, including legitimate negative amounts. Unknown data is not zero measured performance. LIMIT affects displayed rows only; totals retain full filtered scope. Currency-grouped totals never combine denominations. Cost Category removal changes the export schema while retaining rows and financial evidence.

Remaining historical Ruff debt is 2313 configured violations; no repository-wide cosmetic cleanup attempted. The per-file/rule baseline prevents count increases, not every possible same-count replacement; fatal correctness rules remain a separate zero-tolerance gate. Four-file strict typing skips imported modules, so this is not whole-repository type safety.

Python 3.9/3.11/3.13 runtime CI jobs are pending external execution. POSIX filesystem enforcement cannot be verified on this Windows host (BLOCKED subcheck). All reported PASS finding statuses mean implemented and locally verified to the stated scope; these two limitations are not converted into passing runtime evidence.

Alias derivation bounds Python batch memory; DuckDB retains full mapping tables, DISTINCT operations and integrity projections, and residual source-identifier sets still grow with cardinality. The 10,000-row synthetic case demonstrates correctness/batching, not enterprise-scale throughput. Arbitrary customer labels in unclassified prose cannot be inferred; export schema is fail-closed and known patterns are supported, but review before sharing remains necessary.

Breaking/compatibility changes: incomplete execution exits 2; MCP unavailable/partial status replaces misleading ok; required privacy failures withhold output and suppress raw worker errors; MCP SDK 2 is excluded; None/N/A replaces unsupported scores and mixed-currency aggregate totals; calendar-current and latest-available are distinct; ended months have unknown finality; Cost Category columns dropped, unknown SAFE suffixes block; text CSV formula cells gain a protective apostrophe. No new AWS actions, telemetry or automatic network checks.

## Exact changed-file inventory

- `.github/workflows/ci.yml`
- `docs/audit/stabilization-4252c6c.md`
- `kulshan/docs/architecture.md`
- `kulshan/docs/audit/redaction-surface.md`
- `kulshan/docs/mcp-integration.md`
- `kulshan/docs/reckoner-cost-semantics.md`
- `kulshan/mypy-stabilization.ini`
- `kulshan/pyproject.toml`
- `kulshan/src/kulshan/analyze/export.py`
- `kulshan/src/kulshan/billing_integrity.py`
- `kulshan/src/kulshan/checks/cost/__init__.py`
- `kulshan/src/kulshan/checks/cost/analyzers/advanced.py`
- `kulshan/src/kulshan/checks/cost/analyzers/efficiency.py`
- `kulshan/src/kulshan/checks/cost/analyzers/waste.py`
- `kulshan/src/kulshan/checks/cost/cost_fetcher.py`
- `kulshan/src/kulshan/checks/cost/reporters/exporter.py`
- `kulshan/src/kulshan/checks/cost/reporters/html_report.py`
- `kulshan/src/kulshan/checks/cost/reporters/terminal.py`
- `kulshan/src/kulshan/cli.py`
- `kulshan/src/kulshan/csv_safety.py`
- `kulshan/src/kulshan/export/batching.py`
- `kulshan/src/kulshan/export/columns.py`
- `kulshan/src/kulshan/export/cur_export.py`
- `kulshan/src/kulshan/export/gates.py`
- `kulshan/src/kulshan/mcp_server/tools.py`
- `kulshan/src/kulshan/orchestrator.py`
- `kulshan/src/kulshan/pseudonym/classifier.py`
- `kulshan/src/kulshan/pseudonym/engine.py`
- `kulshan/src/kulshan/reckoner/cli.py`
- `kulshan/src/kulshan/reckoner/contracts.py`
- `kulshan/src/kulshan/reckoner/cost/semantics.py`
- `kulshan/src/kulshan/reckoner/query.py`
- `kulshan/src/kulshan/reckoner/registries.py`
- `kulshan/src/kulshan/reckoner/renderers.py`
- `kulshan/src/kulshan/reckoner/terminal.py`
- `kulshan/src/kulshan/redact.py`
- `kulshan/src/kulshan/report/csv_export.py`
- `kulshan/src/kulshan/report/html.py`
- `kulshan/src/kulshan/report/terminal.py`
- `kulshan/tests/unit/test_billing_integrity.py`
- `kulshan/tests/unit/test_consultant_export.py`
- `kulshan/tests/unit/test_mcp_execution.py`
- `kulshan/tests/unit/test_mcp_privacy.py`
- `kulshan/tests/unit/test_reckoner_contracts.py`
- `kulshan/tests/unit/test_stabilization.py`
- `kulshan/tests/unit/test_stabilization_finance.py`
- `kulshan/tests/unit/test_stabilization_scale.py`
- `kulshan/tools/check_ruff_baseline.py`
- `kulshan/tools/ruff-baseline.json`

## Independent-audit blocker repair (2026-10-17)

The four original PASS claims above were inaccurate at ffd7b70. The independent audit demonstrated dropped column names in package metadata, semantic identifier leaks at the MCP boundary, consolidated clean-plus-denied results presented as complete, and unsupported 72/C executive scoring. Those claims are replaced with the targeted regression evidence in commit `7c463d8`; the earlier logs remain historical evidence, not proof of these repairs.

| Blocker | Reproduced before | Repair | Regression evidence | Result |
|---|---|---|---|---|
| Consultant metadata | Yes, actual ZIP leaked the dropped name | Ordinal removed-column labels in every package serializer and schema gate; no regex workaround in Gate 3 | test_merge_blockers.py::test_actual_zip_omits_dropped_column_names; existing consultant tests | PASS |
| MCP identifiers | Yes, named resources and numeric account fields escaped the boundary | Semantic field classes, numeric identifier aliases, nested/grouped/ranked rows, cross-field text references, retained compaction semantics | test_mcp_merge_blockers.py: six different returned JSON payloads plus fail-closed and schema checks | PASS |
| Consolidated completeness | Yes, clean + skipped/denied merged to complete/100/0 | Shared completeness, per-source evidence, missing connection/pack representation, CUR metadata and exit correction | test_consolidated_coverage (five combinations), test_cur_only_cli_failure, test_failed_connection_keeps_missing_evidence, test_merge_preserves_source_detail_without_mutating_inputs, three presentation formats | PASS |
| Executive score eligibility | Yes, empty evidence produced 72/C | Explicit eligibility; unavailable shape includes null score, N/A grade, empty pillars; valid inputs retain calculation | test_executive_scoring_eligibility (empty, partial, missing, unavailable, valid) | PASS |

### Repair validation

Interpreter P remains `.venv/Scripts/python.exe`, root working directory except where noted. All tests use mocks/local synthetic files and local subprocesses. No live AWS access. Logs are in ignored `.audit-tmp/four-blockers-*.log`.

- Initial red command: `P -m pytest -c kulshan/pyproject.toml kulshan/tests/unit/test_merge_blockers.py kulshan/tests/unit/test_mcp_merge_blockers.py --tb=short`: pytest exit 1, 15 failed, 3 passed. Numeric semantic assertions were strengthened subsequently to require a string alias, rather than merely scanning string results.
- First repaired focused run of those two files: exit 0, 18 passed. Additional real CLI, serializer/schema and provenance checks were added afterward.
- Affected suites: `P -m pytest -c kulshan/pyproject.toml kulshan/tests/unit/test_merge_blockers.py kulshan/tests/unit/test_mcp_merge_blockers.py kulshan/tests/unit/test_consultant_export.py kulshan/tests/unit/test_pseudonym_engine.py kulshan/tests/unit/test_privacy_output.py kulshan/tests/unit/test_reckoner_cost_semantics.py kulshan/tests/unit/test_output_integrity.py kulshan/tests/unit/test_workspace_execution.py --tb=short`: exit 0, 228 passed, no skips. The preceding run had 225 passed and two failures: the new HTML test used the Windows default encoding, and an old schema-gate test expected disclosed dropped names. The test was corrected to read UTF-8 and the obsolete privacy expectation was replaced.
- Focused blocker/MCP gate: `P -m pytest -c kulshan/pyproject.toml kulshan/tests/unit/test_merge_blockers.py kulshan/tests/unit/test_mcp_merge_blockers.py kulshan/tests/unit/test_mcp_execution.py kulshan/tests/unit/test_mcp_privacy.py --tb=short`: exit 0, 48 passed, no skips. Includes real local stdio initialization and seven-tool discovery. The subsequent source-detail immutability regression is included in the full run.
- **One full suite after implementation:** `P -m pytest -c kulshan/pyproject.toml kulshan/tests --disable-warnings --tb=short -rs`: exit 0, **690 passed, 1 skipped**, 19.88 seconds. Skip remains test_pseudonym_secret.py:47 (POSIX permission enforcement is not available on Windows); it is not a PASS.
- `P kulshan/tools/check_ruff_baseline.py`: exit 0, 2313 configured residual violations versus 2318 historical baseline (no baseline expansion). `P -m ruff check --select E9,F63,F7,F82 kulshan/src kulshan/tests`: exit 0. No repository-wide lint cleanup or renewed debt audit.
- From kulshan/: `../.venv/Scripts/python.exe -m mypy --config-file mypy-stabilization.ini`: exit 0, four focused files. A first shell invocation from root used the wrong relative interpreter path; corrected working-directory invocation passed.
- From kulshan/: `../.venv/Scripts/python.exe -m build`: exit 0, wheel and sdist 0.6.2 built.
- `.audit-venv/stabilization-wheel/Scripts/python.exe -m pip install --no-deps --force-reinstall ./kulshan/dist/kulshan-0.6.2-py3-none-any.whl`: exit 0, using the existing isolated dependency environment. `python -m pip check`: exit 0, no broken requirements. Installed CLI --version and --help: exit 0; version 0.6.2. Installed-wheel FastMCP registration/discovery: seven tools, exit 0. No new dependency audit or fresh dependency-resolution claim.

### Intentional compatibility changes and limits

- Exported dropped-column lists now contain ordinal labels such as removed_column_0001; original names remain internal for validation. Counts and treatment remain available, but customer-defined removed names cannot be reconstructed from the package.
- Numeric identifier fields become string aliases. Financial metrics/counts/quantities retain numeric types and values. Compact MCP findings add resource_id/account_id keys so semantic information is retained until sanitization. Arrays/dictionaries and non-sensitive keys are preserved; ranked [identifier, amount] rows retain the amount.
- Named identifiers in semantic fields can also be replaced in human-readable text references. Unknown arbitrary prose without semantic context or supported patterns still cannot be inferred reliably. No raw fallback was added.
- Consolidated results add coverage_by_source, source_connections and the unavailable status. A conservative minimum represents complete multi-account pack scores; partial/unavailable scores are null/N/A. JSON top-level unavailable scores are null and terminal/HTML show Unavailable. CLI incomplete execution remains exit 2. Existing connection authentication failures remain nonzero.
- Executive unavailable results preserve composite_grade/headline/pillars keys; valid inputs report assessed status. No score is derived from absent measurements.

All four targeted blockers are locally resolved to the scope above. Remaining limits from the original stabilization still apply: remote Python CI matrix execution is not verified here, the POSIX permission test is skipped on Windows, historical lint debt remains, and export residual identifier sets/DuckDB operations remain cardinality-dependent. Final status: READY FOR INDEPENDENT AUDIT, not a merge authorization.

Additional changed files for this repair: `kulshan/src/kulshan/consolidated.py`, `kulshan/src/kulshan/coverage.py`, `kulshan/src/kulshan/export/package.py`, `kulshan/tests/unit/test_merge_blockers.py`, `kulshan/tests/unit/test_mcp_merge_blockers.py`. Other repaired files already appear in the original inventory above.

## Scoped MCP cross-field repair (2026-10-17)

The final audit of `0b4d520` confirmed the four original counterexamples passed, but found a new P1 output-integrity defect: learned resource names were substituted into every string, including authoritative severity and currency values. The earlier broad MCP PASS claim did not establish schema integrity. This section supersedes that claim with commit `e1d1ade` and the narrow validation below; it is not another P0-P3 review.

### Exact change

Only `src/kulshan/pseudonym/engine.py`, `src/kulshan/pseudonym/classifier.py`, the new `tests/unit/test_mcp_field_semantics.py`, and this ledger changed in this repair.

The recursive learned-name replacement is now `_protect_prose_references`, which carries field context. Already-pseudonymized identifier fields and declared schema metadata are excluded from that pass. The classifier explicitly includes currency, status/state, grade, and AWS region metadata forms as passthrough contexts. Numeric account IDs still use semantic ACCOUNT classification; numerical metrics and booleans remain unchanged. Property names are not rewritten by learned-name substitution. Existing direct-pattern scanning and the required active-engine MCP boundary remain in place.

Distinctive known names may be aliased in human-readable/unknown prose fields. Short/common names and names resembling region codes are ambiguous in prose, so matching prose is returned as `[PROSE_WITHHELD]` rather than guessing at meaning. This is an intentional reduction of prose content, not an identifier or field-type fallback. Identifiers themselves still receive workspace-secret-derived deterministic aliases. No mutable workspace state or alias scheme was changed.

### Before/after evidence

- Before the fix: `P -m pytest -c kulshan/pyproject.toml kulshan/tests/unit/test_mcp_field_semantics.py -k preserves --tb=short` returned pytest exit 1: **9 failed, 1 passed, 11 deselected**. The high/USD examples failed because metadata severity/currency were replaced with resource aliases. Cost was the sole pre-fix passing collision because that fixture's structured cost value was numeric.
- After the fix: all ten collision names (`high`, `critical`, `low`, `USD`, `CAD`, `cost`, `complete`, `unknown`, `EC2`, `us-east-1`) pass simultaneous assertions on final returned MCP JSON. Resource/account/nested/grouped identifiers are aliases, metadata and numerical values are unchanged, object keys/array shapes are retained, repeated same-secret responses agree, and a different secret produces different aliases. Each name also has a failure-injection case requiring the final boundary to withhold output.
- Separate direct calls to the final MCP `_private_response` boundary verified both high and USD: resource_id and grouped_resources carried the same safe resource alias; account_id was an account alias; severity=high, currency=USD, confidence=low, status=complete, region=us-east-1, amount=42.5, quantity=12 and enabled=True were simultaneously intact. Ambiguous description text was `[PROSE_WITHHELD]`. This verifies confidentiality and financial/schema integrity together, rather than merely absence of strings from the complete document (legitimate metadata can share the identifier's spelling).

### Validation actually run

`P` is `.venv/Scripts/python.exe`; root working directory unless specified. Logs remain under ignored `.audit-tmp/mcp-field-semantics-*.log`. All tests used offline fixtures/mocks and local subprocesses; no live AWS access.

- MCP/privacy/pseudonymization gate: `P -m pytest -c kulshan/pyproject.toml kulshan/tests/unit/test_mcp_field_semantics.py kulshan/tests/unit/test_mcp_merge_blockers.py kulshan/tests/unit/test_mcp_privacy.py kulshan/tests/unit/test_mcp_execution.py kulshan/tests/unit/test_pseudonym_engine.py --tb=short`: **exit 0, 113 passed, no skips**. Includes the original numeric-account/named-resource/nested-array/free-text cases and local MCP startup/discovery.
- Prior four-blocker regression gate: `P -m pytest -c kulshan/pyproject.toml kulshan/tests/unit/test_merge_blockers.py kulshan/tests/unit/test_mcp_merge_blockers.py kulshan/tests/unit/test_consultant_export.py kulshan/tests/unit/test_stabilization_finance.py kulshan/tests/unit/test_privacy_output.py --tb=short`: **exit 0, 138 passed, no skips**. Includes the actual consultant ZIP, consolidated/CUR CLI failures, eligibility cases and financial/privacy validation.
- **One full suite after final code changes:** `P -m pytest -c kulshan/pyproject.toml kulshan/tests --disable-warnings --tb=short -rs`: **exit 0, 711 passed, 1 skipped**, 27.20 seconds. The only skip is `test_pseudonym_secret.py:47`, POSIX permissions not enforced on Windows; it is not a PASS.
- `P kulshan/tools/check_ruff_baseline.py`: **exit 0**, 2313 historical configured violations against the unchanged 2318 baseline. `P -m ruff check --select E9,F63,F7,F82 kulshan/src kulshan/tests`: **exit 0**. The new long line found on the first gate attempt was wrapped; no baseline expansion or broad cleanup.
- From `kulshan/`: `../.venv/Scripts/python.exe -m mypy --config-file mypy-stabilization.ini`: **exit 0**, existing four-file strict check. This does not establish full-repository or complete privacy-engine type safety.
- `git diff --check`: **exit 0**. No package builds, dependency audits, deployments or releases were performed for this scoped repair; earlier packaging results refer to earlier implementation commits, not the new source revision.

### Remaining limitations and disposition

Unknown arbitrary customer names cannot be inferred reliably without a supported identifier field, recognizable pattern or a known identifier elsewhere in the payload. Ambiguous prose can now be withheld, reducing narrative detail. Direct identifier-pattern handling of dynamic map keys retains its prior behavior; learned common names do not rename schema properties. Existing Windows/POSIX and unexecuted remote Python-matrix limitations remain. No raw privacy fallback was added, and schema preservation does not require stripping legitimate severity/currency values simply because a resource shares their spelling.

This specific P1 regression is locally resolved with simultaneous confidentiality and schema/financial checks. Final status: **READY FOR INDEPENDENT AUDIT**. No push, merge, tag, release, publication or AWS modification.
