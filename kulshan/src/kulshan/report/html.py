"""Self-contained HTML report generator for Kulshan."""
from __future__ import annotations

import html
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from kulshan.__version__ import __version__
from kulshan.orchestrator import TOOL_LABELS, TOOL_ORDER
from kulshan.theme_constants import TOOL_ICONS, GRADE_COLORS_HEX, SEVERITY_COLORS_HEX

# Phase 6C-2: max finding cards rendered per cost subsection.
# Anything beyond this remains in the JSON output.
FINDINGS_PER_SUBSECTION = 25

# Phase 6C-3 follow-up: banner shown above the report header when the caller
# opts in via ``synthetic_sample=True``. Used by the sanitized sample
# generator; never emitted by the production CLI.
_SYNTHETIC_BANNER_HTML = (
    '<div class="synthetic-banner" role="note">'
    '<div class="synthetic-banner-title"><strong>Synthetic sample report</strong></div>'
    '<div class="synthetic-banner-body">'
    'This report uses fixture data only. No customer data, no real AWS '
    'account IDs, and no live AWS environment were used.'
    '</div>'
    '</div>'
)

# Grade color mapping (use shared constants)
_GRADE_COLORS = GRADE_COLORS_HEX

_SEV_COLORS = SEVERITY_COLORS_HEX


def _grade_color(grade: str) -> str:
    """Return hex color for a grade string like A+, B-, etc."""
    if grade in ("N/A", "--"):
        return "#9e9e9e"
    first = grade[0].upper() if grade else "F"
    return _GRADE_COLORS.get(first, "#c62828")


def _svg_dial(score: int, size: int = 120) -> str:
    """Return an inline SVG circle dial for a 0-100 score."""
    score = max(0, min(100, score))
    radius = size * 0.4
    stroke_width = size * 0.08
    cx = size / 2
    cy = size / 2
    circumference = 2 * 3.14159265 * radius
    offset = circumference * (1 - score / 100)
    # Determine color from score
    if score >= 90:
        color = _GRADE_COLORS["A"]
    elif score >= 80:
        color = _GRADE_COLORS["B"]
    elif score >= 70:
        color = _GRADE_COLORS["C"]
    elif score >= 60:
        color = _GRADE_COLORS["D"]
    else:
        color = _GRADE_COLORS["F"]

    return (
        f'<svg width="{size}" height="{size}" viewBox="0 0 {size} {size}" '
        f'class="score-dial" aria-label="Score {score} out of 100">'
        f'<circle cx="{cx}" cy="{cy}" r="{radius}" fill="none" '
        f'stroke="var(--track-color)" stroke-width="{stroke_width}" />'
        f'<circle cx="{cx}" cy="{cy}" r="{radius}" fill="none" '
        f'stroke="{color}" stroke-width="{stroke_width}" '
        f'stroke-dasharray="{circumference}" stroke-dashoffset="{offset:.1f}" '
        f'stroke-linecap="round" '
        f'transform="rotate(-90 {cx} {cy})" />'
        f'<text x="{cx}" y="{cy}" text-anchor="middle" dominant-baseline="central" '
        f'class="dial-text" fill="var(--text-primary)" '
        f'font-size="{size * 0.28}px" font-weight="700">{score}</text>'
        f'</svg>'
    )


def _svg_bar(score: int, width: int = 200, height: int = 12) -> str:
    """Return an inline SVG horizontal bar for a 0-100 score."""
    score = max(0, min(100, score))
    fill_width = int(width * score / 100)
    if score >= 90:
        color = _GRADE_COLORS["A"]
    elif score >= 80:
        color = _GRADE_COLORS["B"]
    elif score >= 70:
        color = _GRADE_COLORS["C"]
    elif score >= 60:
        color = _GRADE_COLORS["D"]
    else:
        color = _GRADE_COLORS["F"]

    rx = height // 2
    return (
        f'<svg width="{width}" height="{height}" '
        f'aria-label="Score bar {score} percent">'
        f'<rect x="0" y="0" width="{width}" height="{height}" rx="{rx}" '
        f'fill="var(--track-color)" />'
        f'<rect x="0" y="0" width="{fill_width}" height="{height}" rx="{rx}" '
        f'fill="{color}" />'
        f'</svg>'
    )


def generate_html_report(
    results: dict,
    overall_score: int,
    overall_grade: str,
    account_id: str,
    regions: list,
    duration_secs: float,
    top_actions: Optional[List[dict]] = None,
    synthetic_sample: bool = False,
) -> str:
    """Return a complete self-contained HTML string for the Kulshan Report.

    When ``synthetic_sample=True`` a banner is rendered above the header
    declaring the report uses fixture data. Used by the sample generator;
    the CLI never sets this.
    """
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    esc = html.escape

    # Build tool scorecards
    tool_cards_html = _build_tool_cards(results)

    # Build severity summary
    severity_html = _build_severity_summary(results)

    # Phase 6C-2: ranked Top Actions table (empty string when no findings).
    top_actions_html = _build_top_actions_section(top_actions or [])

    # Commitment KPI + Money on Fire sections (from cost pack data)
    commitment_kpi_html = _build_commitment_kpi(results)
    money_on_fire_html = _build_money_on_fire(results, top_actions or [])

    # Build per-tool detail sections (cost pack gets findings + overlap inline)
    details_html = _build_tool_details(results)

    # Synthetic-sample banner: opt-in, default off.
    synthetic_banner_html = _SYNTHETIC_BANNER_HTML if synthetic_sample else ""

    # Overall dial
    hero_dial = _svg_dial(overall_score, size=180)
    hero_color = _grade_color(overall_grade)

    return _HTML_TEMPLATE.format(
        css=_CSS,
        js=_JS,
        version=esc(__version__),
        account_id=esc(str(account_id)),
        regions_count=len(regions),
        duration=f"{duration_secs:.1f}",
        timestamp=esc(timestamp),
        hero_dial=hero_dial,
        overall_grade=esc(overall_grade),
        hero_color=hero_color,
        overall_score=overall_score,
        tool_cards=tool_cards_html,
        severity_summary=severity_html,
        top_actions_section=top_actions_html,
        commitment_kpi_section=commitment_kpi_html,
        money_on_fire_section=money_on_fire_html,
        tool_details=details_html,
        synthetic_banner=synthetic_banner_html,
    )


def _build_tool_cards(results: dict) -> str:
    """Build the grid of tool scorecard HTML."""
    cards: list[str] = []
    for key in TOOL_ORDER:
        result = results.get(key, {})
        scores = result.get("scores", {})
        skipped = result.get("skipped", False)
        label = TOOL_LABELS.get(key, key)
        icon = TOOL_ICONS.get(key, "")
        score = scores.get("overall_score", 0)
        grade = scores.get("grade", "N/A")
        findings = scores.get("total_findings", 0)
        color = _grade_color(grade)

        if skipped:
            dial = _svg_dial(0, size=90)
            cards.append(
                f'<div class="tool-card skipped">'
                f'<div class="tool-icon">{icon}</div>'
                f'<div class="tool-name">{html.escape(label)}</div>'
                f'<div class="tool-dial">{dial}</div>'
                f'<div class="tool-grade" style="color:#9e9e9e">N/A</div>'
                f'<div class="tool-findings">Skipped</div>'
                f'</div>'
            )
        else:
            dial = _svg_dial(score, size=90)
            cards.append(
                f'<div class="tool-card">'
                f'<div class="tool-icon">{icon}</div>'
                f'<div class="tool-name">{html.escape(label)}</div>'
                f'<div class="tool-dial">{dial}</div>'
                f'<div class="tool-grade" style="color:{color}">{html.escape(grade)}</div>'
                f'<div class="tool-findings">{findings} finding{"s" if findings != 1 else ""}</div>'
                f'</div>'
            )
    return "\n".join(cards)


def _build_severity_summary(results: dict) -> str:
    """Build severity badge HTML."""
    totals: Dict[str, int] = {"critical": 0, "high": 0, "medium": 0, "low": 0}
    for result in results.values():
        if result.get("skipped"):
            continue
        sev = result.get("scores", {}).get("severity_counts", {})
        for k in totals:
            totals[k] += int(sev.get(k, 0))

    badges: list[str] = []
    for level, count in totals.items():
        color = _SEV_COLORS[level]
        badges.append(
            f'<span class="sev-badge" style="background:{color}">'
            f'{level.capitalize()}: {count}</span>'
        )
    return "\n".join(badges)


def _build_tool_details(results: dict) -> str:
    """Build expandable per-tool detail sections."""
    sections: list[str] = []
    for key in TOOL_ORDER:
        result = results.get(key, {})
        scores = result.get("scores", {})
        skipped = result.get("skipped", False)
        label = TOOL_LABELS.get(key, key)
        icon = TOOL_ICONS.get(key, "")
        score = scores.get("overall_score", 0)
        grade = scores.get("grade", "N/A")
        errors = result.get("errors", [])
        color = _grade_color(grade)
        bar = _svg_bar(score, width=300, height=14)

        status = "Skipped" if skipped else f"{score}/100"

        # Build breakdown rows from scores dict (exclude known meta keys)
        meta_keys = {"overall_score", "grade", "total_findings", "severity_counts"}
        breakdown_rows: list[str] = []
        for k, v in scores.items():
            if k in meta_keys:
                continue
            if isinstance(v, (int, float)):
                sub_bar = _svg_bar(int(v), width=200, height=10)
                breakdown_rows.append(
                    f'<tr><td class="detail-label">{html.escape(str(k))}</td>'
                    f'<td class="detail-score">{v}</td>'
                    f'<td>{sub_bar}</td></tr>'
                )

        breakdown_table = ""
        if breakdown_rows:
            breakdown_table = (
                '<table class="breakdown-table">'
                '<thead><tr><th>Category</th><th>Score</th><th></th></tr></thead>'
                '<tbody>' + "\n".join(breakdown_rows) + '</tbody></table>'
            )

        # Phase 6C-2: cost pack gets findings + overlap summary inline.
        pack_extras = ""
        if key == "cost" and not skipped:
            pack_extras = _build_cost_findings_section(result)

        error_html = ""
        if errors:
            error_items = "\n".join(
                f"<li>{html.escape(str(e))}</li>" for e in errors
            )
            error_html = f'<div class="error-list"><strong>Errors / Warnings:</strong><ul>{error_items}</ul></div>'

        sections.append(
            f'<details class="tool-detail">'
            f'<summary>'
            f'<span class="detail-icon">{icon}</span>'
            f'<span class="detail-name">{html.escape(label)}</span>'
            f'<span class="detail-grade" style="color:{color}">{html.escape(grade)}</span>'
            f'<span class="detail-status">{status}</span>'
            f'</summary>'
            f'<div class="detail-body">'
            f'<div class="detail-bar">{bar}</div>'
            f'{breakdown_table}'
            f'{pack_extras}'
            f'{error_html}'
            f'</div>'
            f'</details>'
        )
    return "\n".join(sections)


# ── Commitment KPI + Money on Fire sections ──────────────────────────────────


def _build_commitment_kpi(results: dict) -> str:
    """Build the Commitment Health KPI section from cost pack breakdown data."""
    cost_result = results.get("cost") or {}
    if cost_result.get("skipped"):
        return ""

    scores = cost_result.get("scores", {})
    breakdown = scores.get("breakdown", {})
    if not breakdown:
        return ""

    # Extract commitment metrics from the breakdown
    ri_coverage = breakdown.get("ri_coverage_pct", 0)
    sp_utilization = breakdown.get("sp_utilization_pct", 0)
    sp_coverage = breakdown.get("sp_coverage_pct", 0)
    unused_commitment = breakdown.get("unused_commitment_usd", 0)

    # If no meaningful data, skip
    if ri_coverage == 0 and sp_utilization == 0 and sp_coverage == 0:
        return ""

    # Build progress bars
    def _kpi_bar(value: float, target: float = 80, label: str = "", suffix: str = "%") -> str:
        pct = min(100, max(0, value))
        color = "#2e7d32" if pct >= target else "#f57f17" if pct >= target * 0.7 else "#c62828"
        return (
            f'<div class="kpi-row">'
            f'<span class="kpi-label">{label}</span>'
            f'<div class="kpi-bar-track">'
            f'<div class="kpi-bar-fill" style="width:{pct}%;background:{color}"></div>'
            f'<div class="kpi-target-line" style="left:{target}%"></div>'
            f'</div>'
            f'<span class="kpi-value">{value:.0f}{suffix}</span>'
            f'</div>'
        )

    rows = []
    if ri_coverage > 0:
        rows.append(_kpi_bar(ri_coverage, 80, "RI Coverage"))
    if sp_coverage > 0:
        rows.append(_kpi_bar(sp_coverage, 70, "SP Coverage"))
    if sp_utilization > 0:
        rows.append(_kpi_bar(sp_utilization, 90, "SP Utilization"))

    unused_html = ""
    if unused_commitment > 0:
        unused_html = f'<div class="kpi-unused">Unused commitment: <strong>${unused_commitment:,.0f}/mo</strong></div>'

    if not rows:
        return ""

    return (
        '<h2 class="section-title">Commitment Health</h2>\n'
        '<div class="commitment-kpi">\n'
        + "\n".join(rows)
        + unused_html
        + '\n</div>'
    )


def _build_money_on_fire(results: dict, top_actions: list) -> str:
    """Build the Money on Fire hero section showing total addressable savings."""
    # Sum up all monthly savings from findings across all packs
    total_savings = 0.0
    savings_by_source: dict = {}

    for f in top_actions:
        impact = 0.0
        try:
            impact = float(f.get("estimated_monthly_impact", 0) or 0)
        except (TypeError, ValueError):
            pass
        if impact > 0:
            total_savings += impact
            pack = f.get("pack", "other")
            savings_by_source[pack] = savings_by_source.get(pack, 0) + impact

    # Also include sweep monthly_waste if available
    sweep_result = results.get("sweep") or {}
    sweep_waste = sweep_result.get("scores", {}).get("monthly_waste", 0) or 0
    if sweep_waste > 0 and "sweep" not in savings_by_source:
        total_savings += sweep_waste
        savings_by_source["sweep"] = sweep_waste

    if total_savings < 1:
        return ""

    # Build breakdown rows
    source_labels = {
        "cost": "Cost anomalies & rightsizing",
        "sweep": "Orphaned resources",
        "security": "Security risk reduction",
        "dr": "DR improvements",
        "limit": "Quota optimization",
    }

    breakdown_rows = []
    for pack, amount in sorted(savings_by_source.items(), key=lambda x: -x[1]):
        label = source_labels.get(pack, pack.capitalize())
        breakdown_rows.append(
            f'<div class="mof-row">'
            f'<span class="mof-label">{html.escape(label)}</span>'
            f'<span class="mof-amount">${amount:,.0f}/mo</span>'
            f'</div>'
        )

    breakdown_html = "\n".join(breakdown_rows) if breakdown_rows else ""

    return (
        '<div class="money-on-fire">\n'
        f'<div class="mof-hero">'
        f'<span class="mof-icon">🔥</span>'
        f'<span class="mof-total">${total_savings:,.0f}<span class="mof-per">/month</span></span>'
        f'</div>\n'
        f'<div class="mof-subtitle">Total addressable savings identified</div>\n'
        f'<div class="mof-breakdown">{breakdown_html}</div>\n'
        '</div>'
    )


# ── Phase 6C-2: top actions + cost findings + overlap helpers ────────────────


def _source_label(kind: str) -> str:
    """Map finding kind → display source label. Mirrors terminal renderer."""
    if isinstance(kind, str) and kind.startswith("anomaly_aws_native"):
        return "AWS"
    return "Kulshan"


def _money(v: Any) -> str:
    """Format a numeric value as ``$1,234.56``. Empty string on bad input."""
    try:
        return f"${float(v):,.2f}"
    except (TypeError, ValueError):
        return ""


def _pct(v: Any) -> str:
    """Format a 0-1 confidence as ``95%``. Empty string on bad input."""
    try:
        return f"{float(v) * 100:.0f}%"
    except (TypeError, ValueError):
        return ""


def _truncate(text: str, max_len: int = 200) -> str:
    """Truncate long strings with an ellipsis."""
    if not isinstance(text, str):
        text = str(text)
    if len(text) <= max_len:
        return text
    return text[: max_len - 1].rstrip() + "…"


def _build_top_actions_section(top_actions: List[dict]) -> str:
    """Ranked Top Actions table. Returns empty string when no actions."""
    if not top_actions:
        return ""

    rows: list[str] = []
    for i, f in enumerate(top_actions, start=1):
        sev = str(f.get("severity") or "info")
        sev_color = _SEV_COLORS.get(sev, "#9e9e9e")
        impact = _money(f.get("estimated_monthly_impact"))
        conf = _pct(f.get("confidence"))
        source = _source_label(str(f.get("kind") or ""))
        title = html.escape(_truncate(str(f.get("title") or ""), 160))
        rec = f.get("recommended_action") or ""
        rec_html = (
            f'<div class="ta-rec">{html.escape(_truncate(str(rec), 220))}</div>'
            if rec
            else ""
        )
        rows.append(
            f'<tr class="ta-row">'
            f'<td class="ta-rank">{i}</td>'
            f'<td><span class="sev-pill" style="background:{sev_color}">'
            f'{html.escape(sev.capitalize())}</span></td>'
            f'<td class="ta-impact">{impact}</td>'
            f'<td class="ta-conf">{conf}</td>'
            f'<td class="ta-source">{html.escape(source)}</td>'
            f'<td><div class="ta-title">{title}</div>{rec_html}</td>'
            f'</tr>'
        )

    return (
        '<h2 class="section-title">Top Actions</h2>\n'
        '<table class="top-actions-table">\n'
        '<thead><tr>'
        '<th>#</th><th>Severity</th><th>Monthly impact</th>'
        '<th>Confidence</th><th>Source</th><th>Action</th>'
        '</tr></thead>\n'
        '<tbody>\n' + "\n".join(rows) + '\n</tbody>\n'
        '</table>'
    )


def _build_cost_findings_section(cost_result: dict) -> str:
    """Overlap summary + grouped finding cards for the cost pack.

    Returns empty string when there are neither findings nor metadata.
    """
    findings = cost_result.get("findings") or []
    metadata = cost_result.get("metadata") or {}
    cad = metadata.get("cost_anomaly_detection")

    if not findings and not cad:
        return ""

    parts: list[str] = []

    if cad:
        parts.append(_build_overlap_summary(cad))

    if findings:
        by_kind: Dict[str, list[dict]] = {}
        for f in findings:
            if not isinstance(f, dict):
                continue
            kind = str(f.get("kind") or "other")
            by_kind.setdefault(kind, []).append(f)

        kind_label = {
            "anomaly_statistical": "Kulshan statistical anomalies",
            "anomaly_aws_native": "AWS-native Cost Anomaly Detection",
        }
        canonical = ["anomaly_statistical", "anomaly_aws_native"]
        rendered: set[str] = set()
        for kind in canonical:
            if kind in by_kind:
                parts.append(
                    _build_findings_subsection(kind_label[kind], by_kind[kind])
                )
                rendered.add(kind)
        for kind, fs in by_kind.items():
            if kind in rendered:
                continue
            parts.append(
                _build_findings_subsection(f"Other cost findings ({kind})", fs)
            )

    return '<div class="cost-findings">\n' + "\n".join(parts) + "\n</div>"


def _build_findings_subsection(label: str, findings: list) -> str:
    """One labeled subsection of finding cards, capped at FINDINGS_PER_SUBSECTION."""
    total = len(findings)
    shown = findings[:FINDINGS_PER_SUBSECTION]
    cards = "\n".join(_build_finding_card(f) for f in shown)
    truncation = ""
    if total > FINDINGS_PER_SUBSECTION:
        truncation = (
            f'<p class="findings-truncation">'
            f'Showing {FINDINGS_PER_SUBSECTION} of {total}. Full list in JSON.'
            f'</p>'
        )
    return (
        f'<h3 class="findings-subsection">{html.escape(label)}</h3>\n'
        f'<div class="finding-cards">\n{cards}\n</div>\n{truncation}'
    )


def _build_finding_card(f: dict) -> str:
    """One finding rendered as a card. Empty fields omitted."""
    sev = str(f.get("severity") or "info")
    sev_color = _SEV_COLORS.get(sev, "#9e9e9e")
    title = html.escape(str(f.get("title") or ""))
    impact = _money(f.get("estimated_monthly_impact"))
    conf = _pct(f.get("confidence"))

    impact_html = (
        f'<span class="finding-impact">{impact}/mo</span>' if impact else ""
    )
    conf_html = (
        f'<span class="finding-conf">{conf} confidence</span>' if conf else ""
    )

    meta_pairs = (
        ("Account", f.get("account")),
        ("Region", f.get("region")),
        ("Service", f.get("service")),
        ("Usage type", f.get("usage_type")),
        ("Operation", f.get("operation")),
        ("Resource", f.get("resource_id")),
    )
    meta_rows: list[str] = []
    for k, v in meta_pairs:
        if v in (None, "", [], {}):
            continue
        meta_rows.append(
            f"<dt>{html.escape(k)}</dt><dd>{html.escape(str(v))}</dd>"
        )
    meta_html = ""
    if meta_rows:
        meta_html = '<dl class="finding-meta">' + "".join(meta_rows) + "</dl>"

    why = f.get("why_it_matters")
    why_html = (
        f'<p class="finding-why">{html.escape(str(why))}</p>' if why else ""
    )

    rec = f.get("recommended_action")
    rec_html = (
        f'<p class="finding-rec"><strong>Recommended:</strong> '
        f"{html.escape(str(rec))}</p>"
        if rec
        else ""
    )

    evidence = f.get("evidence")
    evidence_html = ""
    if isinstance(evidence, dict) and evidence:
        evidence_html = _build_evidence_block(evidence)

    return (
        '<div class="finding-card">'
        '<div class="finding-head">'
        f'<span class="sev-pill" style="background:{sev_color}">'
        f"{html.escape(sev.capitalize())}</span>"
        f"{impact_html}{conf_html}"
        "</div>"
        f'<div class="finding-title">{title}</div>'
        f"{meta_html}{why_html}{rec_html}{evidence_html}"
        "</div>"
    )


def _build_evidence_block(evidence: dict) -> str:
    """Collapsible evidence as a flat key/value table. No JSON dump."""
    rows: list[str] = []
    for k, v in evidence.items():
        if v in (None, "", [], {}):
            continue
        if isinstance(v, list):
            display = ", ".join(html.escape(str(x)) for x in v)
        elif isinstance(v, dict):
            display = ", ".join(
                f"{html.escape(str(kk))}={html.escape(str(vv))}"
                for kk, vv in v.items()
            )
        else:
            display = html.escape(str(v))
        rows.append(
            f"<tr><th>{html.escape(str(k))}</th><td>{display}</td></tr>"
        )
    if not rows:
        return ""
    return (
        '<details class="finding-evidence">'
        "<summary>Evidence</summary>"
        '<table class="evidence-table">'
        + "".join(rows)
        + "</table>"
        "</details>"
    )


def _build_overlap_summary(cad: dict) -> str:
    """AWS Cost Anomaly Detection vs Kulshan overlap summary block."""
    status = cad.get("status", "")
    anomaly_count = cad.get("anomaly_count")
    lookback_days = cad.get("lookback_days")
    overlap = cad.get("overlap") or {}
    both = overlap.get("both_count", 0)
    reck_only = overlap.get("Kulshan_only_count", 0)
    aws_only = overlap.get("aws_only_count", 0)
    details = cad.get("details") or ""

    status_bits: list[str] = [
        f"AWS Cost Anomaly Detection: <strong>{html.escape(str(status))}</strong>"
    ]
    if isinstance(anomaly_count, int):
        plural = "anomaly" if anomaly_count == 1 else "anomalies"
        status_bits.append(f"{anomaly_count} {plural}")
    if isinstance(lookback_days, int):
        status_bits.append(f"{lookback_days}-day lookback")

    details_html = ""
    if details:
        details_html = (
            f'<div class="overlap-details">{html.escape(str(details))}</div>'
        )

    return (
        '<div class="overlap-summary">'
        f'<div class="overlap-status">{" · ".join(status_bits)}</div>'
        '<div class="overlap-counts">'
        f'<span class="ovc-both">{both} confirmed by Kulshan</span>'
        f'<span class="ovc-reck">{reck_only} Kulshan-only</span>'
        f'<span class="ovc-aws">{aws_only} AWS-only</span>'
        "</div>"
        f"{details_html}"
        "</div>"
    )


# ---------------------------------------------------------------------------
# CSS
# ---------------------------------------------------------------------------
_CSS = """\
:root {
  --bg-primary: #ffffff;
  --bg-secondary: #f5f5f5;
  --bg-card: #ffffff;
  --text-primary: #212121;
  --text-secondary: #616161;
  --border-color: #e0e0e0;
  --track-color: #e0e0e0;
  --shadow: 0 1px 3px rgba(0,0,0,0.1), 0 1px 2px rgba(0,0,0,0.06);
  --shadow-hover: 0 4px 12px rgba(0,0,0,0.1);
}
@media (prefers-color-scheme: dark) {
  :root:not(.light-mode) {
    --bg-primary: #121212;
    --bg-secondary: #1e1e1e;
    --bg-card: #252525;
    --text-primary: #e0e0e0;
    --text-secondary: #9e9e9e;
    --border-color: #333333;
    --track-color: #333333;
    --shadow: 0 1px 3px rgba(0,0,0,0.4);
    --shadow-hover: 0 4px 12px rgba(0,0,0,0.5);
  }
}
.dark-mode {
  --bg-primary: #121212;
  --bg-secondary: #1e1e1e;
  --bg-card: #252525;
  --text-primary: #e0e0e0;
  --text-secondary: #9e9e9e;
  --border-color: #333333;
  --track-color: #333333;
  --shadow: 0 1px 3px rgba(0,0,0,0.4);
  --shadow-hover: 0 4px 12px rgba(0,0,0,0.5);
}
*, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
body {
  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Arial, sans-serif;
  background: var(--bg-primary);
  color: var(--text-primary);
  line-height: 1.5;
  padding: 0;
  margin: 0;
}
.container { max-width: 1100px; margin: 0 auto; padding: 24px 20px; }

/* Header */
.header {
  display: flex; justify-content: space-between; align-items: center;
  padding: 20px 0; border-bottom: 2px solid var(--border-color); margin-bottom: 32px;
}
.header-brand h1 { font-size: 1.6rem; font-weight: 700; letter-spacing: -0.02em; }
.header-brand h1 span { color: #1565c0; }
.header-meta { font-size: 0.82rem; color: var(--text-secondary); text-align: right; line-height: 1.7; }
.theme-toggle {
  background: var(--bg-secondary); border: 1px solid var(--border-color);
  color: var(--text-primary); border-radius: 6px; padding: 6px 12px;
  cursor: pointer; font-size: 0.82rem; margin-left: 12px;
}
.theme-toggle:hover { opacity: 0.8; }

/* Hero */
.hero { text-align: center; padding: 32px 0; }
.hero-grade { font-size: 2.4rem; font-weight: 800; margin-top: 8px; }
.hero-label { font-size: 0.9rem; color: var(--text-secondary); margin-top: 4px; }

/* Section titles */
.section-title {
  font-size: 1.1rem; font-weight: 600; margin: 32px 0 16px;
  padding-bottom: 8px; border-bottom: 1px solid var(--border-color);
}

/* Tool cards grid */
.tool-grid {
  display: grid; grid-template-columns: repeat(auto-fill, minmax(180px, 1fr));
  gap: 16px; margin-bottom: 32px;
}
.tool-card {
  background: var(--bg-card); border: 1px solid var(--border-color);
  border-radius: 10px; padding: 16px; text-align: center;
  box-shadow: var(--shadow); transition: box-shadow 0.2s;
}
.tool-card:hover { box-shadow: var(--shadow-hover); }
.tool-card.skipped { opacity: 0.55; }
.tool-icon { font-size: 1.6rem; margin-bottom: 4px; }
.tool-name { font-size: 0.82rem; font-weight: 600; margin-bottom: 8px; color: var(--text-primary); }
.tool-dial { margin: 0 auto 6px; }
.tool-grade { font-size: 1.1rem; font-weight: 700; }
.tool-findings { font-size: 0.75rem; color: var(--text-secondary); margin-top: 2px; }

/* Severity badges */
.severity-row { display: flex; flex-wrap: wrap; gap: 10px; margin-bottom: 32px; }
.sev-badge {
  color: #fff; padding: 5px 14px; border-radius: 20px;
  font-size: 0.82rem; font-weight: 600;
}

/* Tool details */
.tool-detail {
  background: var(--bg-card); border: 1px solid var(--border-color);
  border-radius: 8px; margin-bottom: 10px; box-shadow: var(--shadow);
}
.tool-detail summary {
  display: flex; align-items: center; gap: 10px;
  padding: 12px 16px; cursor: pointer; font-size: 0.92rem;
  list-style: none; user-select: none;
}
.tool-detail summary::-webkit-details-marker { display: none; }
.tool-detail summary::before {
  content: '\\25B6'; font-size: 0.7rem; transition: transform 0.2s;
  color: var(--text-secondary);
}
.tool-detail[open] summary::before { transform: rotate(90deg); }
.detail-icon { font-size: 1.1rem; }
.detail-name { font-weight: 600; flex: 1; }
.detail-grade { font-weight: 700; font-size: 0.95rem; }
.detail-status { font-size: 0.82rem; color: var(--text-secondary); min-width: 60px; text-align: right; }
.detail-body { padding: 0 16px 16px; }
.detail-bar { margin-bottom: 12px; }
.breakdown-table { width: 100%; border-collapse: collapse; font-size: 0.85rem; margin-bottom: 10px; }
.breakdown-table th { text-align: left; padding: 6px 8px; border-bottom: 1px solid var(--border-color); color: var(--text-secondary); font-weight: 600; }
.breakdown-table td { padding: 5px 8px; border-bottom: 1px solid var(--border-color); }
.detail-label { min-width: 140px; }
.detail-score { min-width: 40px; text-align: right; font-weight: 600; padding-right: 12px !important; }
.error-list { background: var(--bg-secondary); border-radius: 6px; padding: 10px 14px; font-size: 0.82rem; }
.error-list ul { margin: 4px 0 0 18px; }
.error-list li { margin-bottom: 2px; }

/* Footer */
.footer {
  text-align: center; padding: 24px 0; margin-top: 40px;
  border-top: 1px solid var(--border-color);
  font-size: 0.78rem; color: var(--text-secondary); line-height: 1.8;
}

/* Phase 6C-2: Top Actions table */
.top-actions-table {
  width: 100%; border-collapse: collapse; margin-bottom: 32px;
  background: var(--bg-card); border: 1px solid var(--border-color);
  border-radius: 8px; overflow: hidden; box-shadow: var(--shadow);
  font-size: 0.88rem;
}
.top-actions-table thead th {
  text-align: left; padding: 10px 12px; background: var(--bg-secondary);
  border-bottom: 1px solid var(--border-color); color: var(--text-secondary);
  font-weight: 600; font-size: 0.74rem;
  text-transform: uppercase; letter-spacing: 0.04em;
}
.top-actions-table tbody td {
  padding: 10px 12px; border-bottom: 1px solid var(--border-color);
  vertical-align: top;
}
.top-actions-table tbody tr:last-child td { border-bottom: none; }
.ta-rank { font-weight: 700; color: var(--text-secondary); width: 32px; }
.ta-impact { font-variant-numeric: tabular-nums; white-space: nowrap; font-weight: 600; }
.ta-conf { color: var(--text-secondary); white-space: nowrap; }
.ta-source { color: var(--text-secondary); white-space: nowrap; }
.ta-title { font-weight: 600; margin-bottom: 4px; line-height: 1.4; }
.ta-rec { color: var(--text-secondary); font-size: 0.83rem; line-height: 1.4; }

/* Compact severity pill (distinct from .sev-badge used in Severity Summary) */
.sev-pill {
  display: inline-block; color: #fff; padding: 2px 8px; border-radius: 4px;
  font-size: 0.72rem; font-weight: 600;
  text-transform: uppercase; letter-spacing: 0.04em; white-space: nowrap;
}

/* Cost findings cards */
.cost-findings { margin-top: 16px; }
.findings-subsection {
  font-size: 0.95rem; font-weight: 600; margin: 18px 0 10px;
  color: var(--text-primary);
}
.finding-cards { display: flex; flex-direction: column; gap: 10px; }
.finding-card {
  background: var(--bg-secondary); border: 1px solid var(--border-color);
  border-radius: 6px; padding: 12px 14px;
}
.finding-head {
  display: flex; align-items: center; gap: 12px; flex-wrap: wrap;
  margin-bottom: 6px; font-size: 0.82rem;
}
.finding-impact { font-weight: 700; font-variant-numeric: tabular-nums; }
.finding-conf { color: var(--text-secondary); }
.finding-title {
  font-weight: 600; margin-bottom: 8px; line-height: 1.4; font-size: 0.92rem;
}
.finding-meta {
  display: grid; grid-template-columns: max-content 1fr; gap: 2px 14px;
  font-size: 0.82rem; margin-bottom: 8px;
}
.finding-meta dt { color: var(--text-secondary); }
.finding-meta dd { color: var(--text-primary); font-variant-numeric: tabular-nums; }
.finding-why { font-size: 0.85rem; margin-bottom: 6px; line-height: 1.5; }
.finding-rec {
  font-size: 0.85rem; padding: 8px 10px; background: var(--bg-card);
  border-left: 3px solid #1565c0; border-radius: 3px; line-height: 1.5;
  margin-bottom: 8px;
}
.finding-evidence { margin-top: 6px; font-size: 0.82rem; }
.finding-evidence summary {
  cursor: pointer; color: var(--text-secondary); padding: 4px 0; user-select: none;
}
.finding-evidence[open] summary { margin-bottom: 6px; }
.evidence-table {
  width: 100%; border-collapse: collapse; font-size: 0.8rem;
  background: var(--bg-card); border: 1px solid var(--border-color);
  border-radius: 4px; overflow: hidden;
}
.evidence-table th, .evidence-table td {
  padding: 5px 8px; border-bottom: 1px solid var(--border-color);
  text-align: left; vertical-align: top;
}
.evidence-table th {
  background: var(--bg-secondary); color: var(--text-secondary);
  font-weight: 600; min-width: 110px;
}
.evidence-table tr:last-child th, .evidence-table tr:last-child td {
  border-bottom: none;
}
.findings-truncation {
  font-size: 0.8rem; color: var(--text-secondary);
  font-style: italic; margin-top: 8px;
}

/* AWS Cost Anomaly Detection overlap summary */
.overlap-summary {
  background: var(--bg-secondary); border: 1px solid var(--border-color);
  border-radius: 6px; padding: 10px 14px; margin: 12px 0;
  font-size: 0.85rem;
}
.overlap-status { margin-bottom: 4px; }
.overlap-counts {
  display: flex; gap: 16px; flex-wrap: wrap;
  color: var(--text-secondary); font-size: 0.82rem;
}
.overlap-counts span { font-variant-numeric: tabular-nums; }
.overlap-details { margin-top: 6px; font-size: 0.8rem; color: var(--text-secondary); }

/* Synthetic-sample banner (opt-in via synthetic_sample=True) */
.synthetic-banner {
  background: #fff8e1;
  border-bottom: 2px solid #f57f17;
  padding: 14px 24px;
  text-align: center;
  color: #5d4037;
  line-height: 1.5;
}
.synthetic-banner-title {
  font-size: 0.95rem; margin-bottom: 4px;
  letter-spacing: 0.02em;
}
.synthetic-banner-title strong { color: #e65100; }
.synthetic-banner-body { font-size: 0.85rem; max-width: 760px; margin: 0 auto; }
@media (prefers-color-scheme: dark) {
  :root:not(.light-mode) .synthetic-banner {
    background: #2d2418; border-bottom-color: #f57f17; color: #ffe0b2;
  }
}
.dark-mode .synthetic-banner {
  background: #2d2418; border-bottom-color: #f57f17; color: #ffe0b2;
}

/* Print */
@media print {
  body { background: #fff; color: #000; }
  .theme-toggle { display: none; }
  .tool-card { break-inside: avoid; box-shadow: none; border: 1px solid #ccc; }
  .tool-detail { break-inside: avoid; box-shadow: none; }
  .finding-card { break-inside: avoid; }
  .top-actions-table tr { break-inside: avoid; }
  .synthetic-banner { background: #fff8e1; color: #5d4037; }
  .container { max-width: 100%; padding: 0; }
  .footer { border-top: 1px solid #ccc; }
}

/* Commitment KPI */
.commitment-kpi { margin-bottom: 32px; }
.kpi-row {
  display: flex; align-items: center; gap: 12px; margin-bottom: 12px;
  font-size: 0.88rem;
}
.kpi-label { min-width: 120px; font-weight: 600; color: var(--text-primary); }
.kpi-bar-track {
  flex: 1; height: 16px; background: var(--track-color);
  border-radius: 8px; position: relative; overflow: visible;
}
.kpi-bar-fill {
  height: 100%; border-radius: 8px; transition: width 0.3s;
}
.kpi-target-line {
  position: absolute; top: -3px; width: 2px; height: 22px;
  background: var(--text-secondary); opacity: 0.6;
}
.kpi-value { font-weight: 700; min-width: 50px; text-align: right; font-variant-numeric: tabular-nums; }
.kpi-unused {
  margin-top: 8px; padding: 8px 14px; background: var(--bg-secondary);
  border-radius: 6px; font-size: 0.85rem; color: var(--text-secondary);
}

/* Money on Fire */
.money-on-fire {
  background: linear-gradient(135deg, #1a1a2e 0%, #16213e 100%);
  border: 1px solid var(--border-color); border-radius: 12px;
  padding: 28px 32px; margin-bottom: 32px; text-align: center;
}
.mof-hero { display: flex; align-items: center; justify-content: center; gap: 12px; }
.mof-icon { font-size: 2.4rem; }
.mof-total {
  font-size: 2.8rem; font-weight: 800; color: #ff6b35;
  font-variant-numeric: tabular-nums;
}
.mof-per { font-size: 1rem; font-weight: 400; color: var(--text-secondary); margin-left: 4px; }
.mof-subtitle { font-size: 0.9rem; color: var(--text-secondary); margin-top: 8px; }
.mof-breakdown {
  display: flex; flex-direction: column; gap: 6px; margin-top: 16px;
  max-width: 400px; margin-left: auto; margin-right: auto; text-align: left;
}
.mof-row { display: flex; justify-content: space-between; font-size: 0.85rem; }
.mof-label { color: var(--text-secondary); }
.mof-amount { font-weight: 600; color: #ff6b35; font-variant-numeric: tabular-nums; }

/* Responsive */
@media (max-width: 600px) {
  .header { flex-direction: column; text-align: center; gap: 10px; }
  .header-meta { text-align: center; }
  .tool-grid { grid-template-columns: repeat(auto-fill, minmax(140px, 1fr)); }
}
"""

# ---------------------------------------------------------------------------
# JS
# ---------------------------------------------------------------------------
_JS = """\
(function() {
  var btn = document.getElementById('theme-toggle');
  var root = document.documentElement;
  function toggle() {
    if (root.classList.contains('dark-mode')) {
      root.classList.remove('dark-mode');
      root.classList.add('light-mode');
      btn.textContent = 'Dark Mode';
    } else {
      root.classList.remove('light-mode');
      root.classList.add('dark-mode');
      btn.textContent = 'Light Mode';
    }
  }
  btn.addEventListener('click', toggle);
})();
"""

# ---------------------------------------------------------------------------
# HTML template
# ---------------------------------------------------------------------------
_HTML_TEMPLATE = """\
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'; script-src 'unsafe-inline'; img-src data:;">
<title>Kulshan Report</title>
<style>
{css}
</style>
</head>
<body>
{synthetic_banner}
<div class="container">

  <!-- Header -->
  <header class="header">
    <div class="header-brand">
      <h1><span>Kulshan</span> Report</h1>
    </div>
    <div class="header-meta">
      Account: {account_id}<br>
      Regions: {regions_count} | Duration: {duration}s<br>
      {timestamp}
      <button class="theme-toggle" id="theme-toggle">Dark Mode</button>
    </div>
  </header>

  <!-- Overall Score Hero -->
  <section class="hero">
    {hero_dial}
    <div class="hero-grade" style="color:{hero_color}">{overall_grade}</div>
    <div class="hero-label">Overall Operations Score</div>
  </section>

  <!-- Tool Scorecards -->
  <h2 class="section-title">Tool Scores</h2>
  <div class="tool-grid">
    {tool_cards}
  </div>

  <!-- Severity Summary -->
  <h2 class="section-title">Severity Summary</h2>
  <div class="severity-row">
    {severity_summary}
  </div>

  <!-- Top Actions (Phase 6C-2; renders empty string when no findings) -->
  {top_actions_section}

  <!-- Commitment KPIs -->
  {commitment_kpi_section}

  <!-- Money on Fire (total addressable savings) -->
  {money_on_fire_section}

  <!-- Per-Tool Details -->
  <h2 class="section-title">Detailed Results</h2>
  {tool_details}

  <!-- Footer -->
  <footer class="footer">
    Generated by Kulshan v{version}<br>
    {timestamp}<br>
    This report was generated locally. No data was sent to external services.
  </footer>

</div>
<script>
{js}
</script>
</body>
</html>
"""
