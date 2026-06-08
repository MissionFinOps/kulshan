"""Kulshan check packs.

Each subpackage exposes a top-level ``run_scan`` function with the contract:
    run_scan(session, regions, *, quick: bool = False, **kwargs) -> dict

The orchestrator iterates ``TOOL_ORDER`` (defined in Kulshan.orchestrator) and
calls each pack's ``run_scan``. Pack keys are the orchestrator keys used in
TOOL_ORDER, TOOL_LABELS, TOOL_WEIGHTS, and the JSON report shape.
"""
