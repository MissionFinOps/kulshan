"""Generate a one-page executive summary PDF for boardroom delivery."""
from __future__ import annotations

import pandas as pd
from datetime import datetime
from pathlib import Path
from typing import Optional


def _fc(amount: float) -> str:
    if abs(amount) >= 1_000_000:
        return f"${amount / 1_000_000:,.1f}M"
    elif abs(amount) >= 10_000:
        return f"${amount / 1_000:,.1f}K"
    elif abs(amount) >= 1_000:
        return f"${amount:,.0f}"
    return f"${amount:,.2f}"


def generate_summary_pdf(
    path: str,
    data: dict[str, pd.DataFrame],
    days: int,
    anomalies_df: Optional[pd.DataFrame] = None,
    insights: Optional[dict] = None,
    score_data: Optional[dict] = None,
    forecast_df: Optional[pd.DataFrame] = None,
    story: Optional[str] = None,
):
    """Generate a single-page executive summary as HTML, then convert to PDF."""
    try:
        from weasyprint import HTML as WeasyHTML
    except ImportError:
        raise RuntimeError("PDF export requires weasyprint. Install with: pip install weasyprint")

    svc_df = data.get("service", pd.DataFrame())
    total = svc_df["cost"].sum() if not svc_df.empty else 0
    daily_avg = total / max(days, 1)

    # Trend
    trend_text = "Stable"
    trend_color = "#8b949e"
    wow_pct = 0
    if insights:
        trend = insights.get("trend", "stable")
        wow_pct = insights.get("wow_change_pct", 0)
        if trend == "increasing":
            trend_text = f"↑ Increasing ({wow_pct:+.1f}% WoW)"
            trend_color = "#f85149"
        elif trend == "decreasing":
            trend_text = f"↓ Decreasing ({wow_pct:+.1f}% WoW)"
            trend_color = "#3fb950"
        else:
            trend_text = f"→ Stable ({wow_pct:+.1f}% WoW)"

    # Efficiency
    score_html = ""
    if score_data:
        gc = {"A": "#3fb950", "B": "#3fb950", "C": "#d29922", "D": "#f85149", "F": "#f85149"}.get(score_data["grade"], "#8b949e")
        score_html = f'<div class="metric"><div class="metric-value" style="color:{gc}">{score_data["total_score"]}/100</div><div class="metric-label">Efficiency (Grade {score_data["grade"]})</div></div>'

    # Forecast
    forecast_html = ""
    if forecast_df is not None and not forecast_df.empty:
        fc_total = forecast_df["forecast"].sum()
        forecast_html = f'<div class="metric"><div class="metric-value">{_fc(fc_total)}</div><div class="metric-label">30-Day Forecast</div></div>'

    # Top 3 services
    top3_html = ""
    if not svc_df.empty:
        top3 = svc_df.groupby("service")["cost"].sum().sort_values(ascending=False).head(3)
        rows = ""
        for name, cost in top3.items():
            pct = cost / total * 100 if total > 0 else 0
            bar_w = cost / top3.max() * 100 if top3.max() > 0 else 0
            rows += f'<tr><td>{name}</td><td class="r">{_fc(cost)}</td><td class="r">{pct:.0f}%</td><td><div class="bar" style="width:{bar_w:.0f}%"></div></td></tr>'
        top3_html = f'<table><thead><tr><th>Service</th><th>Cost</th><th>%</th><th></th></tr></thead><tbody>{rows}</tbody></table>'

    # Anomalies
    anom_html = '<p style="color:#3fb950">✓ No anomalies detected</p>'
    if anomalies_df is not None and not anomalies_df.empty:
        n = len(anomalies_df)
        crit = len(anomalies_df[anomalies_df["severity"] == "critical"]) if "severity" in anomalies_df.columns else 0
        anom_html = f'<p>⚠️ {n} anomalies ({crit} critical)</p>'
        gc = anomalies_df.columns[0]
        for _, row in anomalies_df.head(3).iterrows():
            anom_html += f'<p class="small">• {row[gc]}: {_fc(row["latest_cost"])} ({row.get("pct_change", 0):+.1f}%)</p>'

    # Recommendations
    recs_html = ""
    po_df = data.get("purchase_option", pd.DataFrame())
    if not po_df.empty:
        od = po_df[po_df["purchase_option"].str.contains("On Demand", case=False, na=False)]
        if not od.empty:
            od_total = od["cost"].sum()
            od_pct = od_total / total * 100 if total > 0 else 0
            if od_pct > 50:
                est = od_total * 0.30
                recs_html += f'<p>💰 {od_pct:.0f}% On-Demand, SP could save ~{_fc(est)}</p>'
    recs_html += '<p>💡 Enable AWS Cost Anomaly Detection for ML alerts</p>'

    html = f"""<!DOCTYPE html><html><head><meta charset="utf-8">
<style>
@page {{ size: A4; margin: 1.5cm; }}
* {{ margin:0; padding:0; box-sizing:border-box; }}
body {{ font-family: -apple-system, 'Segoe UI', sans-serif; color: #1a1a1a; font-size: 11pt; }}
h1 {{ font-size: 18pt; color: #333; margin-bottom: 4px; }}
.subtitle {{ color: #666; font-size: 9pt; margin-bottom: 16px; }}
.metrics {{ display: flex; gap: 12px; margin: 16px 0; }}
.metric {{ flex: 1; background: #f8f9fa; border: 1px solid #dee2e6; border-radius: 8px; padding: 12px; text-align: center; }}
.metric-value {{ font-size: 20pt; font-weight: bold; color: #1f6feb; }}
.metric-label {{ font-size: 8pt; color: #666; margin-top: 4px; }}
h2 {{ font-size: 12pt; color: #1f6feb; margin: 14px 0 6px; border-bottom: 1px solid #dee2e6; padding-bottom: 3px; }}
table {{ width: 100%; border-collapse: collapse; font-size: 9pt; }}
th {{ background: #f1f3f5; padding: 4px 8px; text-align: left; font-weight: 600; }}
td {{ padding: 4px 8px; border-top: 1px solid #e9ecef; }}
.r {{ text-align: right; }}
.bar {{ height: 10px; background: linear-gradient(90deg, #1f6feb, #58a6ff); border-radius: 3px; }}
.story {{ background: #f0f4ff; border-radius: 8px; padding: 10px 14px; font-size: 9.5pt; line-height: 1.5; margin: 10px 0; }}
.small {{ font-size: 8.5pt; color: #555; margin: 2px 0; }}
p {{ margin: 3px 0; font-size: 9.5pt; }}
</style></head><body>
<h1>Cost Analysis, Executive Summary</h1>
<p class="subtitle">Generated {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')} · Last {days} days</p>

<div class="metrics">
  <div class="metric"><div class="metric-value">{_fc(total)}</div><div class="metric-label">Total Spend</div></div>
  <div class="metric"><div class="metric-value">{_fc(daily_avg)}</div><div class="metric-label">Daily Average</div></div>
  <div class="metric"><div class="metric-value" style="color:{trend_color}">{trend_text}</div><div class="metric-label">Trend</div></div>
  {score_html}
  {forecast_html}
</div>

{f'<div class="story">{story}</div>' if story else ''}

<h2>Top Cost Drivers</h2>
{top3_html}

<h2>Anomalies</h2>
{anom_html}

<h2>Recommendations</h2>
{recs_html}

</body></html>"""

    WeasyHTML(string=html).write_pdf(path)
    return path
