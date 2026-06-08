"""AWS-native Cost Anomaly Detection ingestion and overlap classification.

Phase 6B. Wires :func:`cost_fetcher.get_anomalies_from_service` (which calls
``ce:GetAnomalies``) into the normalized :class:`Kulshan.models.Finding`
schema established in Phase 6A, and classifies overlap between Kulshan's
statistical anomalies and AWS's ML-detected anomalies.

This module is internal to the cost check pack. The unified report renderer
sees only ``result["findings"]`` (a list of dicts) and ``result["metadata"]``.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any, Optional

# ── severity / confidence constants ───────────────────────────────────────────
# (impact_threshold_USD, severity), applied in order; first match wins.
# Phase 6 Q1: tunable post-launch.
SEVERITY_THRESHOLDS = (
    (5000.0, "critical"),
    (1000.0, "high"),
    (100.0, "medium"),
    (10.0, "low"),
)

DEFAULT_AWS_CONFIDENCE = 0.85
OVERLAP_BOOSTED_CONFIDENCE = 0.95
OVERLAP_DATE_TOLERANCE_DAYS = 2


def severity_from_impact(total_impact: Any, feedback: str = "") -> str:
    """Derive Finding severity from AWS impact and optional human feedback.

    Feedback ``"YES"`` (user already confirmed the anomaly is real) bumps
    severity to ``"critical"`` regardless of impact (Phase 6 spec §1).
    """
    if (feedback or "").upper() == "YES":
        return "critical"
    try:
        impact = abs(float(total_impact or 0))
    except (TypeError, ValueError):
        impact = 0.0
    for threshold, sev in SEVERITY_THRESHOLDS:
        if impact >= threshold:
            return sev
    return "info"


def _parse_iso_date(s: Any) -> Optional[date]:
    """Best-effort parse of an ISO-format date or datetime string. ``None`` on failure."""
    if s is None or s == "":
        return None
    if isinstance(s, datetime):
        return s.date()
    if isinstance(s, date):
        return s
    text = str(s)
    if "T" in text:
        text = text.split("T", 1)[0]
    try:
        return date.fromisoformat(text)
    except (ValueError, TypeError):
        return None


def _anomaly_days(start: Any, end: Any) -> int:
    """Days the AWS anomaly window spans (inclusive). Returns 1 if undeterminable."""
    s = _parse_iso_date(start)
    e = _parse_iso_date(end)
    if s and e:
        return max((e - s).days, 1)
    return 1


def aws_anomaly_to_finding(aws_row: dict) -> Optional[dict]:
    """Convert an AWS-native anomaly row into a serialized Finding dict.

    Returns ``None`` if the anomaly should be suppressed. Today the only
    suppression rule is ``feedback == "NO"`` (Phase 6 Q3: a human marked the
    anomaly as not-actually-anomalous).
    """
    from kulshan.models import (
        Finding,
        Severity,
        SEVERITY_SCORE_IMPACT,
        compute_fingerprint,
        make_finding_id,
    )

    feedback_raw = aws_row.get("feedback") or ""
    feedback = feedback_raw.upper() if isinstance(feedback_raw, str) else ""
    if feedback == "NO":
        return None

    service = aws_row.get("service") or None
    region = aws_row.get("region") or None
    account = aws_row.get("account") or None
    usage_type = aws_row.get("usage_type") or None
    anomaly_id = aws_row.get("anomaly_id") or ""
    start_date = aws_row.get("start_date") or ""
    end_date = aws_row.get("end_date") or ""

    def _f(key: str) -> float:
        try:
            return float(aws_row.get(key, 0) or 0)
        except (TypeError, ValueError):
            return 0.0

    total_impact = _f("total_impact")
    max_impact = _f("max_impact")
    total_actual = _f("total_actual")
    total_expected = _f("total_expected")

    severity = severity_from_impact(total_impact, feedback)
    days = _anomaly_days(start_date, end_date)

    # Monthly impact proxy: per-day window cost × 30.
    # If both dates are missing, fall back to total_impact directly.
    if start_date or end_date:
        estimated_monthly_impact = round((total_impact / days) * 30.0, 2)
    else:
        estimated_monthly_impact = round(total_impact, 2)

    fingerprint = compute_fingerprint(
        pack="cost",
        kind="anomaly_aws_native",
        account=account,
        service=service,
        usage_type=usage_type,
        period=start_date or end_date,
    )

    # Title
    title_bits = [f"AWS-detected anomaly: {service or 'Unknown service'}"]
    if region:
        title_bits.append(f"in {region}")
    if account:
        title_bits.append(f"account {account}")
    title = ", ".join(title_bits) + f", ${total_impact:,.0f} impact"

    # Description (from anomaly explanation)
    if start_date and end_date and start_date != end_date:
        window = f"{start_date} to {end_date}"
    elif start_date:
        window = start_date
    elif end_date:
        window = end_date
    else:
        window = "the anomaly window"
    description = (
        f"AWS Cost Anomaly Detection ML model flagged "
        f"${total_actual:,.0f} actual vs ${total_expected:,.0f} expected over {window}."
    )

    # Recommended action
    rec_parts = ["Verify in the AWS Cost Anomaly Detection console"]
    if anomaly_id:
        rec_parts.append(f"AnomalyId: {anomaly_id}")
    rec_parts.append("mark feedback if expected.")
    recommended_action = "; ".join(rec_parts)

    # Parse detected_at from start_date
    detected_at = None
    date_str = start_date or end_date
    if date_str:
        from datetime import datetime as _dt
        try:
            detected_at = _dt.fromisoformat(str(date_str))
        except ValueError:
            pass

    finding = Finding(
        id=make_finding_id(pack="cost", kind="anomaly_aws_native", fingerprint=fingerprint),
        pack="cost",
        kind="anomaly_aws_native",
        fingerprint=fingerprint,
        title=title,
        severity=Severity(severity),
        score_impact=SEVERITY_SCORE_IMPACT[severity],
        estimated_monthly_impact=estimated_monthly_impact,
        confidence=DEFAULT_AWS_CONFIDENCE,
        effort="medium",
        risk="safe",
        account_id=account,
        region=region,
        service=service,
        description=description,
        evidence={
            "source": "aws_cost_anomaly_detection",
            "aws_anomaly_id": anomaly_id,
            "start_date": str(start_date),
            "end_date": str(end_date),
            "anomaly_days": days,
            "total_impact": round(total_impact, 2),
            "max_impact": round(max_impact, 2),
            "total_actual": round(total_actual, 2),
            "total_expected": round(total_expected, 2),
            "feedback": feedback_raw,
            "usage_type": usage_type,
        },
        recommended_action=recommended_action,
        compliance_frameworks=[],
        detected_at=detected_at,
        schema_version="2.0",
    )
    return finding.to_dict()


# ── overlap classification ────────────────────────────────────────────────────


def _date_in_window(
    reck_date: Any, aws_start: Any, aws_end: Any, *, tolerance_days: int
) -> bool:
    """``reck_date`` within ``[aws_start - tol, aws_end + tol]``."""
    rd = _parse_iso_date(reck_date)
    s = _parse_iso_date(aws_start)
    e = _parse_iso_date(aws_end)
    if rd is None or s is None or e is None:
        return False
    tol = timedelta(days=tolerance_days)
    return (s - tol) <= rd <= (e + tol)


def matches_overlap(
    reck: dict,
    aws: dict,
    *,
    tolerance_days: int = OVERLAP_DATE_TOLERANCE_DAYS,
) -> bool:
    """Return ``True`` if a Kulshan-statistical finding overlaps an AWS-native finding.

    Match rules (Phase 6 spec §3):

    * Same service (required).
    * Same account if both have one populated (lenient: ``None`` on either side allowed).
    * Kulshan's ``evidence.date`` within ``[aws.start_date − tol, aws.end_date + tol]``.
    """
    r_service = reck.get("service")
    a_service = aws.get("service")
    if not r_service or not a_service or r_service != a_service:
        return False

    r_acct = reck.get("account_id") or reck.get("account")
    a_acct = aws.get("account_id") or aws.get("account")
    if r_acct and a_acct and r_acct != a_acct:
        return False

    reck_date = reck.get("evidence", {}).get("date")
    aws_start = aws.get("evidence", {}).get("start_date") or ""
    aws_end = aws.get("evidence", {}).get("end_date") or aws_start
    return _date_in_window(reck_date, aws_start, aws_end, tolerance_days=tolerance_days)


def classify_findings(reck_findings: list, aws_findings: list) -> dict:
    """Bucket findings into ``both`` / ``Kulshan_only`` / ``aws_only``.

    A Kulshan finding may pair with multiple AWS findings (and vice versa);
    every pairing is recorded in ``both`` as ``(Kulshan_id, aws_id)``. A
    finding ID appears in ``Kulshan_only``/``aws_only`` only when it has zero
    matches.
    """
    pairs: list[tuple[str, str]] = []
    matched_reck: set[str] = set()
    matched_aws: set[str] = set()

    for r in reck_findings:
        for a in aws_findings:
            if matches_overlap(r, a):
                pairs.append((r["id"], a["id"]))
                matched_reck.add(r["id"])
                matched_aws.add(a["id"])

    reck_only = [r["id"] for r in reck_findings if r["id"] not in matched_reck]
    aws_only = [a["id"] for a in aws_findings if a["id"] not in matched_aws]

    return {"both": pairs, "Kulshan_only": reck_only, "aws_only": aws_only}


def apply_overlap_boost(reck_findings: list, aws_findings: list) -> dict:
    """Mutate finding dicts in place: set confidence=0.95 and append ``overlap_with`` IDs.

    Returns the classification dict (same shape as :func:`classify_findings`).
    """
    classification = classify_findings(reck_findings, aws_findings)

    reck_to_aws: dict[str, list[str]] = {}
    aws_to_reck: dict[str, list[str]] = {}
    for r_id, a_id in classification["both"]:
        reck_to_aws.setdefault(r_id, []).append(a_id)
        aws_to_reck.setdefault(a_id, []).append(r_id)

    for r in reck_findings:
        peers = reck_to_aws.get(r["id"], [])
        if peers:
            r["confidence"] = OVERLAP_BOOSTED_CONFIDENCE
            ev = r.setdefault("evidence", {})
            ev["overlap_with"] = list(peers)

    for a in aws_findings:
        peers = aws_to_reck.get(a["id"], [])
        if peers:
            a["confidence"] = OVERLAP_BOOSTED_CONFIDENCE
            ev = a.setdefault("evidence", {})
            ev["overlap_with"] = list(peers)

    return classification
