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
