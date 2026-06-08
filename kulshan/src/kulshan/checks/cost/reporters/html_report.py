"""Generate standalone HTML cost report with segmented trend bars, anomaly cards, and insights."""
from __future__ import annotations

import pandas as pd
import numpy as np
from datetime import datetime
from pathlib import Path
from typing import Optional


def _format_cost_html(amount: float) -> str:
    if abs(amount) >= 1_000_000:
        return f"${amount / 1_000_000:,.1f}M"
    elif abs(amount) >= 10_000:
        return f"${amount / 1_000:,.1f}K"
    elif abs(amount) >= 1_000:
        return f"${amount:,.0f}"
    return f"${amount:,.2f}"


def _segmented_bar_html(daily_costs: list[float], width_pct: float = 100) -> str:
    """Generate a segmented trend bar where each day is a colored div.
    Red = cost increased >10%, Green = decreased >10%, Gray = stable.
    Height proportional to cost magnitude."""
    if not daily_costs or len(daily_costs) < 2:
        return '<div class="seg-bar"><div class="seg" style="width:100%;background:#adb5bd;height:50%"></div></div>'

    max_cost = max(daily_costs) if max(daily_costs) > 0 else 1
    seg_width = width_pct / len(daily_costs)
    segments = []
    for i, cost in enumerate(daily_costs):
        height_pct = max(30, int(cost / max_cost * 100)) if max_cost > 0 else 30
        if i == 0:
            color = "#adb5bd"
        elif cost > daily_costs[i - 1] * 1.10:
            color = "#ff6b6b"
        elif cost < daily_costs[i - 1] * 0.90:
            color = "#51cf66"
        else:
            color = "#adb5bd"
        segments.append(
            f'<div class="seg" style="width:{seg_width:.2f}%;background:{color};height:{height_pct}%"></div>'
        )
    return f'<div class="seg-bar">{"".join(segments)}</div>'


def generate_html_report(
    data: dict[str, pd.DataFrame],
    output_path: str,
    days: int,
    account_names: dict[str, str] | None = None,
    anomalies: Optional[pd.DataFrame] = None,
    insights: Optional[dict] = None,
    story: Optional[str] = None,
    efficiency_score: Optional[dict] = None,
    network_data: Optional[dict] = None,
    forecast_df: Optional[pd.DataFrame] = None,
    marketplace_df: Optional[pd.DataFrame] = None,
):
    """Generate a self-contained HTML report with embedded CSS."""
    sections = []

    # ── Cost Story ────────────────────────────────────────────────────
    if story:
        sections.append(f"""
        <div class="story-card">
            <h2>📖 Cost Story</h2>
            <p>{story}</p>
        </div>""")

    # ── Summary cards ─────────────────────────────────────────────────
    if "service" in data and not data["service"].empty:
        total = data["service"]["cost"].sum()
        num_services = data["service"]["service"].nunique()
        daily_avg = total / max(days, 1)
        sections.append(f"""
        <div class="cards">
            <div class="card"><div class="card-value">{_format_cost_html(total)}</div><div class="card-label">Total Spend</div></div>
            <div class="card"><div class="card-value">{_format_cost_html(daily_avg)}</div><div class="card-label">Daily Average</div></div>
            <div class="card"><div class="card-value">{num_services}</div><div class="card-label">Active Services</div></div>
            <div class="card"><div class="card-value">{days}</div><div class="card-label">Days Analyzed</div></div>
        </div>""")

    # ── Daily Cost Trend Chart (Chart.js) ─────────────────────────────
    if "service" in data and not data["service"].empty:
        daily = data["service"].groupby("date")["cost"].sum().reset_index().sort_values("date")
        if len(daily) > 1:
            chart_labels = [d.strftime("%Y-%m-%d") for d in daily["date"]]
            chart_values = [round(v, 2) for v in daily["cost"].tolist()]
            # 7-day rolling average
            rolling = daily["cost"].rolling(window=7, min_periods=1).mean().round(2).tolist()
            sections.append(f"""
        <h2>📈 Daily Cost Trend</h2>
        <div style="background:var(--card);border:1px solid var(--border);border-radius:8px;padding:1.5rem;margin-bottom:1rem">
            <canvas id="trendChart" height="80"></canvas>
        </div>
        <script>
        new Chart(document.getElementById('trendChart'), {{
            type: 'line',
            data: {{
                labels: {chart_labels},
                datasets: [{{
                    label: 'Daily Cost',
                    data: {chart_values},
                    borderColor: '#58a6ff',
                    backgroundColor: 'rgba(88,166,255,0.1)',
                    fill: true,
                    tension: 0.3,
                    pointRadius: 0,
                    borderWidth: 2
                }}, {{
                    label: '7-Day Average',
                    data: {rolling},
                    borderColor: '#d29922',
                    borderDash: [5,5],
                    fill: false,
                    tension: 0.3,
                    pointRadius: 0,
                    borderWidth: 1.5
                }}]
            }},
            options: {{
                responsive: true,
                plugins: {{ legend: {{ labels: {{ color: '#c9d1d9' }} }} }},
                scales: {{
                    x: {{ ticks: {{ color: '#8b949e', maxTicksLimit: 12 }}, grid: {{ color: '#21262d' }} }},
                    y: {{ ticks: {{ color: '#8b949e', callback: function(v) {{ return '$' + v.toLocaleString() }} }}, grid: {{ color: '#21262d' }} }}
                }}
            }}
        }});
        </script>""")

    # ── Top Services with segmented trend bars ────────────────────────
    if "service" in data and not data["service"].empty:
        df = data["service"]
        totals = df.groupby("service")["cost"].sum().sort_values(ascending=False).head(9)
        grand = totals.sum()
        max_cost = totals.max() if not totals.empty else 0
        rows_html = ""
        for rank, (name, cost) in enumerate(totals.items(), 1):
            pct = cost / grand * 100 if grand > 0 else 0
            bar_w = (cost / max_cost * 100) if max_cost > 0 else 0
            # Build segmented bar from daily data
            grp = df[df["service"] == name].sort_values("date")
            daily_vals = grp["cost"].tolist() if len(grp) > 1 else [cost]
            seg_bar = _segmented_bar_html(daily_vals)
            rows_html += f"""
            <tr>
                <td class="rank">{rank}</td>
                <td>{name}</td>
                <td class="num">{_format_cost_html(cost)}</td>
                <td class="num">{pct:.1f}%</td>
                <td style="width:40%">{seg_bar}</td>
            </tr>"""

        sections.append(f"""
        <h2>Top Services</h2>
        <table>
            <thead><tr><th>#</th><th>Service</th><th>Cost</th><th>% Total</th><th>Trend (Daily)</th></tr></thead>
            <tbody>{rows_html}</tbody>
            <tfoot><tr><td></td><td><strong>Total</strong></td><td class="num"><strong>{_format_cost_html(grand)}</strong></td><td></td><td></td></tr></tfoot>
        </table>""")

    # ── Other dimension tables ────────────────────────────────────────
    for key, title in [
        ("account", "Cost by Account"),
        ("region", "Cost by Region"),
        ("charge_type", "Cost by Charge Type"),
        ("api", "Cost by API/Usage Type"),
    ]:
        if key in data and not data[key].empty:
            df = data[key]
            group_col = key
            totals = df.groupby(group_col)["cost"].sum().sort_values(ascending=False).head(9)
            grand = totals.sum()
            max_cost = totals.max() if not totals.empty else 0
            rows_html = ""
            for name, cost in totals.items():
                label = name
                if key == "account" and account_names and str(name) in account_names:
                    label = f"{account_names[str(name)]} ({name})"
                pct = cost / grand * 100 if grand > 0 else 0
                bar_w = (cost / max_cost * 100) if max_cost > 0 else 0
                rows_html += f"""
                <tr>
                    <td>{label}</td>
                    <td class="num">{_format_cost_html(cost)}</td>
                    <td class="num">{pct:.1f}%</td>
                    <td><div class="bar" style="width:{bar_w:.1f}%"></div></td>
                </tr>"""

            sections.append(f"""
            <h2>{title}</h2>
            <table>
                <thead><tr><th>{group_col.replace('_', ' ').title()}</th><th>Cost</th><th>% Total</th><th>Distribution</th></tr></thead>
                <tbody>{rows_html}</tbody>
                <tfoot><tr><td><strong>Total</strong></td><td class="num"><strong>{_format_cost_html(grand)}</strong></td><td></td><td></td></tr></tfoot>
            </table>""")

    # ── Anomaly Cards ─────────────────────────────────────────────────
    if anomalies is not None and not anomalies.empty:
        severity_colors = {"critical": "#f85149", "warning": "#d29922", "info": "#58a6ff"}
        severity_icons = {"critical": "🔴", "warning": "🟡", "info": "🔵"}
        group_col = anomalies.columns[0]

        # Summary bar
        crit = len(anomalies[anomalies["severity"] == "critical"]) if "severity" in anomalies.columns else 0
        warn = len(anomalies[anomalies["severity"] == "warning"]) if "severity" in anomalies.columns else 0
        info_count = len(anomalies[anomalies["severity"] == "info"]) if "severity" in anomalies.columns else 0

        sections.append(f"""
        <h2>🚨 Anomalies Detected: {len(anomalies)}</h2>
        <div class="cards" style="margin-bottom:1rem">
            <div class="card" style="border-left:4px solid #f85149"><div class="card-value" style="color:#f85149">{crit}</div><div class="card-label">Critical</div></div>
            <div class="card" style="border-left:4px solid #d29922"><div class="card-value" style="color:#d29922">{warn}</div><div class="card-label">Warning</div></div>
            <div class="card" style="border-left:4px solid #58a6ff"><div class="card-value" style="color:#58a6ff">{info_count}</div><div class="card-label">Info</div></div>
        </div>
        <div class="anomaly-grid">""")

        for _, row in anomalies.head(9).iterrows():
            sev = row.get("severity", "info")
            color = severity_colors.get(sev, "#58a6ff")
            icon = severity_icons.get(sev, "🔵")
            pct = row.get("pct_change", 0)
            direction = "↑ Spike" if pct > 0 else "↓ Drop"
            dir_color = "#f85149" if pct > 0 else "#3fb950"
            sections.append(f"""
            <div class="anomaly-card" style="border-left:4px solid {color}">
                <div class="anomaly-header">{icon} {row[group_col]}</div>
                <div class="anomaly-body">
                    <span class="anomaly-cost">{_format_cost_html(row['latest_cost'])}</span>
                    <span style="color:{dir_color}">{direction} ({pct:+.1f}%)</span>
                </div>
                <div class="anomaly-meta">
                    Avg: {_format_cost_html(row['avg_cost'])} · Score: {row.get('score', 0):.1f}σ · {row.get('methods', '')}
                </div>
            </div>""")

        sections.append("</div>")

    # ── Insights ──────────────────────────────────────────────────────
    if insights:
        trend_emoji = {"increasing": "📈", "decreasing": "📉", "stable": "➡️"}.get(insights.get("trend", "stable"), "➡️")
        trend_color = {"increasing": "#f85149", "decreasing": "#3fb950", "stable": "#8b949e"}.get(insights.get("trend", "stable"), "#8b949e")
        wow_pct = insights.get("wow_change_pct", 0)

        insight_items = f"""
        <div class="insight-row"><span>Overall Trend</span><span style="color:{trend_color}">{trend_emoji} {insights.get('trend', 'stable').title()}</span></div>
        <div class="insight-row"><span>Week-over-Week</span><span style="color:{'#f85149' if wow_pct > 0 else '#3fb950'}">{wow_pct:+.1f}%</span></div>
        <div class="insight-row"><span>This Week</span><span>{_format_cost_html(insights.get('current_week_total', 0))}</span></div>
        <div class="insight-row"><span>Last Week</span><span>{_format_cost_html(insights.get('previous_week_total', 0))}</span></div>"""

        if "most_expensive_day" in insights:
            d = insights["most_expensive_day"]
            insight_items += f'\n        <div class="insight-row"><span>💸 Most Expensive Day</span><span>{d["date"]}, {_format_cost_html(d["cost"])}</span></div>'
        if "least_expensive_day" in insights:
            d = insights["least_expensive_day"]
            insight_items += f'\n        <div class="insight-row"><span>💰 Least Expensive Day</span><span>{d["date"]}, {_format_cost_html(d["cost"])}</span></div>'

        if insights.get("most_expensive_dow"):
            insight_items += f'\n        <div class="insight-row"><span>Most Expensive DoW</span><span>{insights["most_expensive_dow"]}</span></div>'
        if insights.get("least_expensive_dow"):
            insight_items += f'\n        <div class="insight-row"><span>Least Expensive DoW</span><span>{insights["least_expensive_dow"]}</span></div>'

        sections.append(f"""
        <h2>🔍 Cost Insights</h2>
        <div class="insights-card">{insight_items}
        </div>""")

    # ── Efficiency Score ──────────────────────────────────────────────
    if efficiency_score:
        total_s = efficiency_score["total_score"]
        grade = efficiency_score["grade"]
        grade_colors = {"A": "#3fb950", "B": "#3fb950", "C": "#d29922", "D": "#f85149", "F": "#f85149"}
        gc = grade_colors.get(grade, "#8b949e")

        breakdown_rows = ""
        for key, item in efficiency_score.get("breakdown", {}).items():
            label = key.replace("_", " ").title()
            bar_pct = item["score"] / item["max"] * 100 if item["max"] > 0 else 0
            bar_color = "#3fb950" if bar_pct >= 70 else ("#d29922" if bar_pct >= 40 else "#f85149")
            breakdown_rows += f"""
            <div class="insight-row">
                <span>{item['status']} {label}</span>
                <span><div style="display:inline-block;width:80px;height:12px;background:#30363d;border-radius:3px;overflow:hidden;vertical-align:middle">
                    <div style="width:{bar_pct:.0f}%;height:100%;background:{bar_color}"></div>
                </div> {item['score']:.0f}/{item['max']}</span>
            </div>"""

        sections.append(f"""
        <h2>🏆 Cost Efficiency Score</h2>
        <div class="cards" style="margin-bottom:1rem">
            <div class="card" style="border-top:4px solid {gc}">
                <div class="card-value" style="color:{gc};font-size:2.5rem">{total_s}/100</div>
                <div class="card-label">Grade: {grade}</div>
            </div>
        </div>
        <div class="insights-card">{breakdown_rows}
        </div>""")

    # ── Network Breakdown ─────────────────────────────────────────────
    if network_data and network_data.get("categories"):
        from ..analyzers.network import get_category_label
        net_total = network_data["grand_total"]
        net_rows = ""
        max_cat = max((c["total"] for c in network_data["categories"].values()), default=0)
        for key, cat in network_data["categories"].items():
            bar_w = (cat["total"] / max_cat * 100) if max_cat > 0 else 0
            net_rows += f"""
            <tr>
                <td>{get_category_label(key)}</td>
                <td class="num">{_format_cost_html(cat['total'])}</td>
                <td class="num">{cat['pct']:.1f}%</td>
                <td><div class="bar" style="width:{bar_w:.1f}%"></div></td>
            </tr>"""

        sections.append(f"""
        <h2>🌐 Network Cost Deep-Dive, {_format_cost_html(net_total)}</h2>
        <table>
            <thead><tr><th>Category</th><th>Cost</th><th>% Network</th><th>Distribution</th></tr></thead>
            <tbody>{net_rows}</tbody>
            <tfoot><tr><td><strong>Total</strong></td><td class="num"><strong>{_format_cost_html(net_total)}</strong></td><td></td><td></td></tr></tfoot>
        </table>""")

    # ── Marketplace Spend ─────────────────────────────────────────────
    if marketplace_df is not None and not marketplace_df.empty:
        _acct_names = account_names or {}
        pivot = marketplace_df.pivot_table(index=["account", "service"], columns="month", values="cost", aggfunc="sum", fill_value=0)
        pivot["total"] = pivot.sum(axis=1)
        pivot = pivot.sort_values("total", ascending=False)
        months = [c for c in pivot.columns if c != "total"]

        mkt_rows = ""
        grand_mkt = 0
        for (acct, svc), row in pivot.iterrows():
            acct_label = _acct_names.get(acct, acct)
            month_cells = "".join(
                f'<td class="num">{_format_cost_html(row[m])}</td>' if row[m] > 0 else '<td class="num" style="color:#484f58">-</td>'
                for m in months
            )
            total = row["total"]
            grand_mkt += total
            mkt_rows += f"<tr><td>{acct_label}</td><td>{svc}</td>{month_cells}<td class='num'><strong>{_format_cost_html(total)}</strong></td></tr>"

        month_headers = "".join(f"<th>{m}</th>" for m in months)
        sections.append(f"""
        <h2>🛒 AWS Marketplace Spend, {_format_cost_html(grand_mkt)}</h2>
        <table>
            <thead><tr><th>Account</th><th>Marketplace Item</th>{month_headers}<th>Total</th></tr></thead>
            <tbody>{mkt_rows}</tbody>
            <tfoot><tr><td><strong>Total</strong></td><td></td>{"".join("<td></td>" for _ in months)}<td class="num"><strong>{_format_cost_html(grand_mkt)}</strong></td></tr></tfoot>
        </table>""")

    # ── Forecast ────────────────────────────────────────────────────────
    if forecast_df is not None and not forecast_df.empty:
        total_fc = forecast_df["forecast"].sum()
        daily_fc = forecast_df["forecast"].mean()
        fc_lines = f"""
        <div class="insight-row"><span>Forecasted Spend ({len(forecast_df)} days)</span><span>{_format_cost_html(total_fc)}</span></div>
        <div class="insight-row"><span>Daily Average</span><span>{_format_cost_html(daily_fc)}</span></div>"""
        if "lower_bound" in forecast_df.columns and "upper_bound" in forecast_df.columns:
            lo = forecast_df["lower_bound"].sum()
            hi = forecast_df["upper_bound"].sum()
            if lo != total_fc or hi != total_fc:
                fc_lines += f"""
        <div class="insight-row"><span>80% Confidence Low</span><span style="color:#3fb950">{_format_cost_html(lo)}</span></div>
        <div class="insight-row"><span>80% Confidence High</span><span style="color:#f85149">{_format_cost_html(hi)}</span></div>"""
        sections.append(f"""
        <h2>🔮 Cost Forecast</h2>
        <div class="insights-card">{fc_lines}
        </div>""")

    # ── Data-Driven Recommendations ───────────────────────────────────
    recs = []
    total_spend = data["service"]["cost"].sum() if "service" in data and not data["service"].empty else 0

    # On-Demand analysis
    if "purchase_option" in data and not data["purchase_option"].empty:
        po = data["purchase_option"]
        od = po[po["purchase_option"].str.contains("On Demand", case=False, na=False)]
        if not od.empty:
            od_total = od["cost"].sum()
            od_pct = od_total / total_spend * 100 if total_spend > 0 else 0
            if od_pct > 50:
                est = od_total * 0.30
                recs.append(f'<div class="rec rec-critical">💰 {od_pct:.0f}% of spend ({_format_cost_html(od_total)}) is On-Demand. '
                            f'A 1-year Compute Savings Plan could save ~{_format_cost_html(est)}. '
                            f'Run: <code>aws ce get-savings-plans-purchase-recommendation</code></div>')

    # Anomaly-driven
    if anomalies is not None and not anomalies.empty and "severity" in anomalies.columns:
        crit = anomalies[anomalies["severity"] == "critical"]
        if len(crit) > 0:
            top_a = crit.iloc[0]
            gc = anomalies.columns[0]
            recs.append(f'<div class="rec rec-critical">🔴 {len(crit)} critical anomalies. '
                        f'Top: {top_a[gc]} at {_format_cost_html(top_a["latest_cost"])} '
                        f'({top_a.get("pct_change", 0):+.1f}% vs avg). Check CloudTrail.</div>')

    # Network
    if network_data and network_data.get("grand_total", 0) > 500:
        net_pct = network_data["grand_total"] / total_spend * 100 if total_spend > 0 else 0
        recs.append(f'<div class="rec rec-info">🌐 Network costs: {_format_cost_html(network_data["grand_total"])} '
                    f'({net_pct:.0f}% of total). Review NAT Gateways and data transfer patterns.</div>')

    # Fallback
    if not recs:
        recs.append('<div class="rec rec-info">✅ No critical issues. Cost posture looks healthy.</div>')

    recs.append('<div class="rec rec-info">💡 Enable AWS Cost Anomaly Detection for ML-based alerts.</div>')
    recs.append('<div class="rec rec-info">💡 Set up AWS Budgets for proactive cost control.</div>')

    sections.append(f"""
    <h2>📋 Recommendations</h2>
    {''.join(recs)}""")

    # ── Assemble HTML ─────────────────────────────────────────────────
    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Cost Analysis Report</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.7/dist/chart.umd.min.js"></script>
<style>
:root {{ --bg: #0d1117; --card: #161b22; --border: #30363d; --text: #c9d1d9; --accent: #58a6ff; --green: #3fb950; --red: #f85149; --yellow: #d29922; }}
* {{ margin:0; padding:0; box-sizing:border-box; }}
body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background: var(--bg); color: var(--text); padding: 2rem; max-width: 1200px; margin: 0 auto; }}
h1 {{ background: linear-gradient(135deg, #667eea, #764ba2); -webkit-background-clip: text; -webkit-text-fill-color: transparent; font-size: 2rem; margin-bottom: 0.3rem; }}
h2 {{ color: var(--accent); margin: 2.5rem 0 1rem; border-bottom: 1px solid var(--border); padding-bottom: 0.5rem; font-size: 1.3rem; }}
.subtitle {{ color: #8b949e; margin-bottom: 2rem; }}
.cards {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(160px, 1fr)); gap: 1rem; margin: 1.5rem 0; }}
.card {{ background: var(--card); border: 1px solid var(--border); border-radius: 8px; padding: 1.2rem; text-align: center; }}
.card-value {{ font-size: 1.6rem; font-weight: bold; color: var(--accent); }}
.card-label {{ color: #8b949e; margin-top: 0.4rem; font-size: 0.85rem; }}
.story-card {{ background: linear-gradient(135deg, rgba(102,126,234,0.1), rgba(118,75,162,0.1)); border: 1px solid var(--border); border-radius: 12px; padding: 1.5rem 2rem; margin: 1.5rem 0; }}
.story-card h2 {{ border: none; margin: 0 0 0.8rem; padding: 0; }}
.story-card p {{ line-height: 1.7; font-size: 1.05rem; }}
table {{ width: 100%; border-collapse: collapse; background: var(--card); border-radius: 8px; overflow: hidden; margin-bottom: 1rem; }}
th {{ background: #21262d; padding: 0.75rem 1rem; text-align: left; font-weight: 600; color: var(--accent); font-size: 0.85rem; text-transform: uppercase; letter-spacing: 0.5px; }}
td {{ padding: 0.6rem 1rem; border-top: 1px solid var(--border); }}
.rank {{ color: #8b949e; width: 30px; }}
.num {{ text-align: right; font-variant-numeric: tabular-nums; }}
.bar {{ height: 16px; background: linear-gradient(90deg, #1f6feb, #58a6ff); border-radius: 3px; min-width: 2px; }}
.seg-bar {{ display: flex; align-items: flex-end; height: 35px; border-radius: 8px; overflow: hidden; background: rgba(255,255,255,0.03); }}
.seg {{ min-width: 1px; transition: height 0.2s; }}
tfoot td {{ border-top: 2px solid var(--border); }}
.anomaly-grid {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(320px, 1fr)); gap: 1rem; }}
.anomaly-card {{ background: var(--card); border: 1px solid var(--border); border-radius: 8px; padding: 1rem 1.2rem; }}
.anomaly-header {{ font-weight: 600; margin-bottom: 0.5rem; font-size: 0.95rem; }}
.anomaly-body {{ display: flex; justify-content: space-between; align-items: baseline; margin-bottom: 0.4rem; }}
.anomaly-cost {{ font-size: 1.3rem; font-weight: bold; color: var(--accent); }}
.anomaly-meta {{ color: #8b949e; font-size: 0.8rem; }}
.insights-card {{ background: var(--card); border: 1px solid var(--border); border-radius: 8px; padding: 1rem 0; }}
.insight-row {{ display: flex; justify-content: space-between; padding: 0.6rem 1.5rem; border-bottom: 1px solid var(--border); }}
.insight-row:last-child {{ border-bottom: none; }}
.rec {{ padding: 0.8rem 1.2rem; margin: 0.5rem 0; border-radius: 6px; background: var(--card); border: 1px solid var(--border); }}
.rec-critical {{ border-left: 4px solid var(--red); }}
.rec-info {{ border-left: 4px solid var(--accent); }}
@media print {{ body {{ background: white; color: #1a1a1a; }} .card, .anomaly-card, .insights-card, .story-card, .rec, table {{ background: #f8f9fa; border-color: #dee2e6; }} h1 {{ -webkit-text-fill-color: #333; }} h2 {{ color: #333; }} }}
@media (max-width: 768px) {{ body {{ padding: 1rem; }} .cards {{ grid-template-columns: repeat(2, 1fr); }} .anomaly-grid {{ grid-template-columns: 1fr; }} }}
</style>
</head>
<body>
<h1>Cost Analysis Report</h1>
<p class="subtitle">Generated {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')} · Last {days} days</p>
{''.join(sections)}
</body></html>"""

    Path(output_path).write_text(html, encoding="utf-8")
    return output_path
