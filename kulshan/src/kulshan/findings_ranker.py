"""Composite priority ranking for normalized findings.

Phase 6C-1. Surfaces the most important findings across all check packs by a
deterministic composite score. Used by:

* ``cli.py`` to populate the JSON ``top_actions`` array
* ``report/terminal.py`` to render the Top Actions panel
* (later) ``report/html.py`` to render the Top Actions section

The ranker is intentionally simple. No ML, no learned weights. Tunable via the
constants at the top of this module.
"""
from __future__ import annotations

from typing import Any

# ── tunables ──────────────────────────────────────────────────────────────────

# Weight of each contributing factor. Must sum to 1.00.
WEIGHT_IMPACT = 0.40
WEIGHT_SEVERITY = 0.25
WEIGHT_CONFIDENCE = 0.20
WEIGHT_LOW_EFFORT = 0.10
WEIGHT_LOW_RISK = 0.05

# Findings with monthly impact >= IMPACT_CAP all score equally on the impact
# axis. Prevents a single $1M anomaly from drowning out a $9K one with much
# higher severity / confidence.
IMPACT_CAP = 10_000.0

# Severity → weight (Phase 6 finding vocabulary).
SEVERITY_WEIGHT = {
    "critical": 1.00,
    "high":     0.75,
    "medium":   0.50,
    "low":      0.25,
    "info":     0.00,
}

# Effort → weight. Lower effort earns higher priority (we invert at use site).
EFFORT_WEIGHT = {
    "trivial": 0.00,
    "low":     0.33,
    "medium":  0.66,
    "high":    1.00,
}

# Risk → weight. Lower risk earns higher priority (we invert at use site).
RISK_WEIGHT = {
    "safe":   0.00,
    "low":    0.33,
    "medium": 0.66,
    "high":   1.00,
}


def _safe_float(v: Any, default: float = 0.0) -> float:
    try:
        return float(v) if v is not None else default
    except (TypeError, ValueError):
        return default


def priority(finding: dict) -> float:
    """Composite priority in roughly ``[0, 1]``. Higher = more important.

    Missing / unknown fields default to safe values:

    * missing impact → 0
    * missing severity / unknown severity → 0
    * missing confidence → 0
    * missing effort / unknown → ``"medium"`` (penalty of 0.66)
    * missing risk / unknown → ``"safe"`` (no penalty)

    Implementations should not depend on the exact returned magnitude, only
    on its ordering across findings within the same scan.
    """
    impact = max(_safe_float(finding.get("estimated_monthly_impact"), 0.0), 0.0)
    impact_norm = min(impact, IMPACT_CAP) / IMPACT_CAP

    sev = SEVERITY_WEIGHT.get(finding.get("severity", "info"), 0.0)
    conf = max(0.0, min(1.0, _safe_float(finding.get("confidence"), 0.0)))
    eff = EFFORT_WEIGHT.get(finding.get("effort", "medium"), 0.66)
    risk = RISK_WEIGHT.get(finding.get("risk", "safe"), 0.0)

    return (
        impact_norm * WEIGHT_IMPACT
        + sev * WEIGHT_SEVERITY
        + conf * WEIGHT_CONFIDENCE
        + (1.0 - eff) * WEIGHT_LOW_EFFORT
        + (1.0 - risk) * WEIGHT_LOW_RISK
    )


def flatten_findings(results: dict) -> list:
    """Concatenate ``result["findings"]`` across every pack into one flat list.

    Packs that don't emit findings (or emit ``None``) contribute nothing. Order
    follows ``results.items()`` order, then per-pack order, this is **not**
    the ranked order; ranking happens in :func:`top_n`.
    """
    out: list = []
    if not isinstance(results, dict):
        return out
    for pack_result in results.values():
        if not isinstance(pack_result, dict):
            continue
        pack_findings = pack_result.get("findings") or []
        for f in pack_findings:
            if isinstance(f, dict):
                out.append(f)
    return out


def top_n(findings: list, n: int = 10) -> list:
    """Return the top ``n`` findings by composite priority, deterministic tie-break.

    Tie-break: priority desc → estimated_monthly_impact desc → id asc. The id
    is a stable hash (Phase 6A fingerprint), so ties resolve identically across
    scans with the same inputs.
    """
    if not findings:
        return []
    if n is None or n < 0:
        return []

    def _key(f: dict) -> tuple:
        return (
            -priority(f),
            -max(_safe_float(f.get("estimated_monthly_impact"), 0.0), 0.0),
            str(f.get("id", "")),
        )

    return sorted(findings, key=_key)[:n]
