"""Adapter layer for converting pack-internal finding dicts to the canonical shape.

Packs can be migrated incrementally. Until a pack emits canonical findings
directly, this adapter handles the translation from its internal
representation to the canonical Finding dict shape defined in ``models.py``.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from kulshan.models import (
    CONFIDENCE_ENUM_MAP,
    SEVERITY_SCORE_IMPACT,
    VALID_EFFORT,
    VALID_RISK,
    VALID_SEVERITY,
    compute_fingerprint,
    make_finding_id,
)

# ---------------------------------------------------------------------------
# Mapping tables
# ---------------------------------------------------------------------------

EFFORT_MINUTES_MAP: Dict[str, tuple] = {
    "trivial": (0, 15),
    "low": (16, 60),
    "medium": (61, 240),
    "high": (241, None),
}
"""Maps effort category → (min_minutes, max_minutes). max=None means unbounded."""


def _effort_from_minutes(minutes: int) -> str:
    """Bucket an effort_minutes integer into a categorical effort string."""
    if minutes <= 15:
        return "trivial"
    elif minutes <= 60:
        return "low"
    elif minutes <= 240:
        return "medium"
    else:
        return "high"


# Default values for fields missing from the raw finding.
DEFAULTS: Dict[str, Any] = {
    "effort": "medium",
    "risk": "safe",
    "confidence": 0.5,
    "estimated_monthly_impact": 0.0,
    "description": "",
    "evidence": {},
    "recommended_action": "",
    "compliance_frameworks": [],
    "schema_version": "2.0",
}

# The canonical keys that belong on a Finding dict (used to detect extras).
_CANONICAL_KEYS = frozenset({
    "id", "pack", "kind", "fingerprint",
    "title", "severity", "score_impact",
    "estimated_monthly_impact", "confidence",
    "effort", "risk",
    "account_id", "region", "resource_arn", "resource_type", "service",
    "description", "evidence", "recommended_action",
    "compliance_frameworks", "detected_at", "schema_version",
})

# Keys that are recognized as aliases/legacy names (not extras).
_ALIAS_KEYS = frozenset({
    "tool", "check_id", "monthly_impact_usd", "effort_minutes",
    "account", "usage_type", "operation", "resource_id",
    "why_it_matters", "remediation_text", "owner_hint",
})


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def adapt(pack: str, raw_finding: dict) -> dict:
    """Convert a pack-internal finding dict to the canonical shape.

    Parameters
    ----------
    pack : str
        The pack name (e.g. "cost", "security"). Used as fallback for the
        ``pack`` field and for fingerprint computation.
    raw_finding : dict
        The raw finding dict emitted by the pack's internal logic.

    Returns
    -------
    dict
        A canonical finding dict suitable for validation and ``Finding.from_dict()``.
    """
    raw = dict(raw_finding)  # shallow copy to avoid mutating caller's dict
    out: Dict[str, Any] = {}

    # --- Identity -----------------------------------------------------------

    # Map tool → pack, check_id → kind
    out["pack"] = raw.pop("pack", None) or raw.pop("tool", None) or pack
    out["kind"] = raw.pop("kind", None) or raw.pop("check_id", None) or "unknown"

    # --- Severity -----------------------------------------------------------

    sev_raw = raw.pop("severity", "info")
    if hasattr(sev_raw, "value"):
        # Enum instance (e.g. Severity.HIGH)
        sev_str = str(sev_raw.value).lower()
    else:
        sev_str = str(sev_raw).lower()

    if sev_str not in VALID_SEVERITY:
        sev_str = "info"
    out["severity"] = sev_str

    # --- score_impact (derived from severity) -------------------------------

    out["score_impact"] = SEVERITY_SCORE_IMPACT.get(out["severity"], 0)

    # --- Confidence ---------------------------------------------------------

    conf_raw = raw.pop("confidence", None)
    if conf_raw is None:
        out["confidence"] = DEFAULTS["confidence"]
    elif isinstance(conf_raw, (int, float)):
        val = float(conf_raw)
        out["confidence"] = max(0.0, min(1.0, val))
    elif isinstance(conf_raw, str):
        out["confidence"] = CONFIDENCE_ENUM_MAP.get(conf_raw.lower(), DEFAULTS["confidence"])
    else:
        out["confidence"] = DEFAULTS["confidence"]

    # --- Impact (monthly_impact_usd Decimal string → float) -----------------

    impact_raw = raw.pop("estimated_monthly_impact", None)
    if impact_raw is None:
        impact_raw = raw.pop("monthly_impact_usd", None)

    if impact_raw is not None:
        try:
            out["estimated_monthly_impact"] = float(str(impact_raw))
        except (ValueError, TypeError):
            out["estimated_monthly_impact"] = DEFAULTS["estimated_monthly_impact"]
    else:
        out["estimated_monthly_impact"] = DEFAULTS["estimated_monthly_impact"]

    # --- Effort (effort string or effort_minutes bucketing) -----------------

    effort_raw = raw.pop("effort", None)
    effort_minutes_raw = raw.pop("effort_minutes", None)

    if effort_raw is not None and str(effort_raw) in VALID_EFFORT:
        out["effort"] = str(effort_raw)
    elif effort_minutes_raw is not None:
        try:
            minutes = int(effort_minutes_raw)
            out["effort"] = _effort_from_minutes(minutes)
        except (ValueError, TypeError):
            out["effort"] = DEFAULTS["effort"]
    else:
        out["effort"] = DEFAULTS["effort"]

    # --- Risk ---------------------------------------------------------------

    risk_raw = raw.pop("risk", None)
    if risk_raw is not None and str(risk_raw) in VALID_RISK:
        out["risk"] = str(risk_raw)
    else:
        out["risk"] = DEFAULTS["risk"]

    # --- Title --------------------------------------------------------------

    out["title"] = raw.pop("title", "")

    # --- Location -----------------------------------------------------------

    out["account_id"] = raw.pop("account_id", None) or raw.pop("account", None)
    out["region"] = raw.pop("region", None)
    out["resource_arn"] = raw.pop("resource_arn", None) or raw.pop("resource_id", None)
    out["resource_type"] = raw.pop("resource_type", None)
    out["service"] = raw.pop("service", None)

    # --- Explanation --------------------------------------------------------

    out["description"] = raw.pop("description", None) or raw.pop("why_it_matters", None) or DEFAULTS["description"]
    out["evidence"] = raw.pop("evidence", None)
    if not isinstance(out["evidence"], dict):
        out["evidence"] = {}
    out["recommended_action"] = raw.pop("recommended_action", None) or raw.pop("remediation_text", None) or DEFAULTS["recommended_action"]

    # --- Metadata -----------------------------------------------------------

    out["compliance_frameworks"] = list(raw.pop("compliance_frameworks", DEFAULTS["compliance_frameworks"]))
    out["detected_at"] = raw.pop("detected_at", None)
    out["schema_version"] = raw.pop("schema_version", DEFAULTS["schema_version"])

    # --- Fingerprint (compute if absent) ------------------------------------

    fingerprint = raw.pop("fingerprint", None)
    if not fingerprint:
        fingerprint = compute_fingerprint(
            pack=out["pack"],
            kind=out["kind"],
            account=out["account_id"],
            service=out["service"],
            usage_type=raw.pop("usage_type", None),
            period=out["detected_at"],
        )
    else:
        # Still pop usage_type if present to avoid it ending up in extras
        raw.pop("usage_type", None)
    out["fingerprint"] = fingerprint

    # --- ID (compute if absent) ---------------------------------------------

    id_raw = raw.pop("id", None)
    if id_raw:
        out["id"] = id_raw
    else:
        out["id"] = make_finding_id(
            pack=out["pack"],
            kind=out["kind"],
            fingerprint=out["fingerprint"],
        )

    # --- Preserve unrecognized fields in evidence["extra"] ------------------

    # Remove any remaining known alias keys that were already handled
    for alias_key in list(raw.keys()):
        if alias_key in _ALIAS_KEYS:
            raw.pop(alias_key, None)

    # Whatever remains in raw is unrecognized / extra
    if raw:
        extra = out["evidence"].get("extra", {})
        extra.update(raw)
        out["evidence"]["extra"] = extra

    return out
