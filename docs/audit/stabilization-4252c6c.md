# Stabilization of 4252c6c

Branch: `fix/p0-p3-stabilization`. Starting commit: `4252c6ca76be8e6fd186dc61915c8799653d50ff`.
Ending commit: pending. Offline mocks and fixtures only; no live AWS validation.

## Milestone 1

P0-01, P1-01, P1-02, P1-03, P1-04: implemented; focused validation passed (final verification pending).
P1-05, P2-01, P2-02, P2-03, P2-04, P2-05, P2-06, P2-07, P3-01, P3-02, P3-03, P3-04, P3-05, P3-06: NOT DONE (in progress).

Baseline command: `.venv/Scripts/python.exe -m pytest kulshan/tests -q --disable-warnings --tb=short > baseline-stabilization.log 2>&1` stalled with no output; interrupted, exit 1. Not a PASS. Root pytest config enables coverage. Baseline Ruff JSON saved locally in `ruff-baseline-stabilization.json`.

Initial regressions: 19 failed, 5 passed (expected red).
Pass 1 command: `.venv/Scripts/python.exe -m pytest -c kulshan/pyproject.toml kulshan/tests/unit/test_mcp_execution.py kulshan/tests/unit/test_mcp_privacy.py kulshan/tests/unit/test_stabilization.py -k 'not prior_month and not customer_text and not residual_ipv6' --tb=short`: exit 0; 41 passed, 4 deselected; no skips.
MCP installation: `pip install -e "./kulshan[mcp]" "mcp>=1.0,<2"`: exit 0; installed MCP 1.30.0; tool discovery test passes (7 tools).

Changes: cost CostFetcher and run_scan preserve injected session; standalone profile remains available. Orchestrator summary adds unavailable status. CLI incomplete execution exits 2. MCP dynamic responses require active pseudonymization; worker errors suppress raw diagnostics; clean scans distinguish unavailable/partial. Unsupported MCP installations fail collection instead of skipping.

Regression files: `kulshan/tests/unit/test_stabilization.py`, `test_mcp_privacy.py`, `test_mcp_execution.py`.

## Milestone 2

Pass 2 command: `.venv/Scripts/python.exe -m pytest -c kulshan/pyproject.toml kulshan/tests/unit/test_stabilization.py kulshan/tests/unit/test_stabilization_finance.py kulshan/tests/unit/test_stabilization_scale.py kulshan/tests/unit/test_consultant_export.py kulshan/tests/unit/test_privacy_output.py kulshan/tests/unit/test_reckoner_query.py kulshan/tests/unit/test_billing_integrity.py --tb=short`: exit 0, 153 passed, no skips. Normal temporary-file permissions were required; sandbox attempts produced fixture setup permission errors, not passing tests.

P1-05 and P2-01 through P2-07 implemented. Added period discovery, shared currency validation, unlimited totals, unknown billing finality, withheld unsupported efficiency scores, CSV protection, and unknown-field redaction. Consultant classification now blocks unknown suffixes instead of broad SAFE prefixes. Compatibility: partial scans exit 2; new unavailable coverage; unknown finality; None efficiency and mixed-currency totals; previously accepted unknown export columns may block. Mapping construction now uses 2048-value batches independently in transformation and integrity validation; no enterprise throughput claims. Test transport wrappers expose DuckDB cursors accordingly.

P3-01: added core CI matrix 3.9/3.11/3.13 and separate MCP 3.12 job. Locally available interpreters are 3.12 and 3.14; matrix has not executed locally. MCP SDK compatibility on Python 3.9 is not claimed.
P3-02: baseline measured 2318 configured Ruff violations. Per-file/rule no-increase gate added; fatal-rule gate retained. Focused strict typing targets CSV safety, alias batching, billing integrity and semantic query execution; imports skipped, not whole-repository type safety.
P3-03: no source import/use of Jinja2 or PyJWT; removed direct dependencies. Retained awscrt for botocore credential support (including modern login paths); package verification pending.
P3-04: synthetic 10,000 distinct-identifier alias test, independent row-equivalence tests; full residual identifier set and DuckDB map storage remain cardinality-dependent.
P3-05: architecture, MCP, Reckoner cost semantics, redaction surface updated.
P3-06: final packaging/trust validation pending.
