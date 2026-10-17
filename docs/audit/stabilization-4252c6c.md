# Kulshan stabilization: 4252c6c

Branch: `fix/p0-p3-stabilization`.
Starting commit: `4252c6ca76be8e6fd186dc61915c8799653d50ff`.
Ending implementation commit: `4a3650a` (the subsequent audit-only commit records this ledger).
Implementation commits: `12e4409`, `a57ab49`, `21dfa99`, `4a3650a`.

All validation used offline mocks, fixtures or local package artifacts. No live AWS calls, pushes, merges, releases, tags, deployments or publishing. The three protected untracked user files were never modified or staged.

## Finding results

Paths in this table are relative to `kulshan/`; the complete exact changed-file inventory follows.

| Finding | Status | Implementation and regression evidence |
|---|---|---|
| P0-01 | PASS | `src/kulshan/checks/cost/cost_fetcher.py`, `checks/cost/__init__.py`: injected session is authoritative for CE and Organizations; standalone profiles retained. `test_stabilization.py`: direct/profile sessions, constructor fallback rejection, missing credentials, pack forwarding, and mocked cross-account AssumeRole through create_session. Adjacent cost paths inspected: no other client/session constructors bypass it. Existing workspace execution tests cover connection/account selection. |
| P1-01 | PASS | `pyproject.toml`: MCP >=1.0,<2 in mcp/dev extras. Installed 1.30.0. `test_mcp_execution.py` only skips when top-level optional mcp is absent; incompatible installed SDK fails import. `.github/workflows/ci.yml` adds explicit extra job. `test_mcp_privacy.py` tests registration and real local stdio initialization/list_tools. |
| P1-02 | PASS | `mcp_server/tools.py` reuses orchestrator summary for report/quick security: complete/partial/unavailable, retains partial findings and missing-permission coverage. Success, zero findings, denied/skipped, partial scans tested in `test_mcp_privacy.py`. |
| P1-03 | PASS | All six dynamic tools pass mandatory parent `_private_response` before external return. Missing/inactive/failing engine or invalid response withholds output. Raw worker diagnostics and invalid pack strings are not echoed. Common identifier patterns include accountless ARNs, network IDs and IPv6; numbers remain numerical. Every dynamic operation and privacy failure tested in `test_mcp_privacy.py`; static list_packs contains no dynamic input. |
| P1-04 | PASS | `orchestrator.py`, `cli.py`, `report/html.py`, `report/terminal.py`: common completeness/exit policy; partial/unavailable exits 2, critical findings 1, complete otherwise 0. Incomplete pack scores become None/N/A and progress reports partial coverage. `test_stabilization.py`, existing output/CLI/workspace regressions. |
| P1-05 | PASS | `export/columns.py`: no broad SAFE prefix inheritance; closed vocabulary. Cost Category columns DROP (headers can leak labels), line descriptions pseudonymized whole. Unknown suffixes block unless explicitly dropped. `export/gates.py`: IPv6 residual check. Existing consultant synthetic projects/accounts/ARNs/IDs and multiset integrity tests retained; `test_stabilization.py` adds risky column/IPv6 checks. |
| P2-01 | PASS | `reckoner/query.py`, `contracts.py`, `registries.py`: calendar-current UTC month, separate latest-available month, explicit half-open custom ranges. Historical December/January fixture distinguishes current October from latest January. `test_stabilization_finance.py`; updated stable vocabulary regression. |
| P2-02 | PASS | Shared `reckoner/cost/semantics.py:validate_currencies` used by high-level executor. Missing currency rejected, mixed currency requires grouping, totals remain separate by currency. Lower-level mixed-currency total is None. `test_stabilization_finance.py` and existing canonical-cost suite. |
| P2-03 | PASS | Independent aggregate before LIMIT with same range/filters/exclusions. Currency-grouped totals and terminal presentation retained. `test_stabilization_finance.py` verifies visible-row count and full total. |
| P2-04 | PASS | `billing_integrity.py`: ended month means unknown finality, never calendar-derived trust. Validates period month; CE/CUR corroboration is not independent verification. `test_billing_integrity.py`, `test_stabilization.py`. No invoice-reconciliation workflow added. |
| P2-05 | PASS | `checks/cost/analyzers/{efficiency,advanced,waste}.py`, cost pack and reporters: missing RI/SP inputs explicitly unknown; unsupported composite/stability/waste scores withheld; low spend is only a review candidate. `test_stabilization_scale.py` tests absent inputs and commitment/idle claims. |
| P2-06 | PASS | `csv_safety.py` shared by findings, Reckoner and legacy cost CSV writers. Formula prefixes and leading whitespace protected; signed numeric strings and numerical values unchanged. `test_stabilization.py`, existing CSV/privacy suites. |
| P2-07 | PASS | `redact.py`, `pseudonym/{classifier,engine}.py`: unknown strings/map keys scan supported identifiers, IPv6, accountless ARNs, temporary keys; labeled secrets protected without matching every 40-character hash. Strong required CLI/investigation/query privacy cannot silently fall back. `test_stabilization.py`, pseudonym/privacy suites. |
| P3-01 | PASS | Core CI matrix added: Python 3.9/3.11/3.13; MCP job Python 3.12. Locally executed 3.12.10; 245 source files parse under 3.9?3.13 grammar. Remote matrix execution is pending; static parsing is not runtime proof. MCP optional extra is not claimed for Python 3.9. |
| P3-02 | PASS | Measured baseline 2318 Ruff violations; final 2314. Fatal rules pass. `tools/check_ruff_baseline.py` rejects increases per file/rule using `tools/ruff-baseline.json`; CI runs both. Focused strict mypy covers CSV protection, alias batching, billing integrity and query execution. Imports skipped; no whole-repository typing claim. |
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
- **Final full suite:** `P -m pytest -c kulshan/pyproject.toml kulshan/tests --disable-warnings --tb=short -rs > final-stabilization-tests.log 2>&1`: exit 0, **663 passed, 1 skipped**, 16.53 seconds. Skip: `test_pseudonym_secret.py:47`, POSIX permissions not enforced on Windows. This check remains unverified locally; Linux CI is configured to exercise it.
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

Remaining historical Ruff debt is 2314 configured violations; no repository-wide cosmetic cleanup attempted. The per-file/rule baseline prevents count increases, not every possible same-count replacement; fatal correctness rules remain a separate zero-tolerance gate. Four-file strict typing skips imported modules, so this is not whole-repository type safety.

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
