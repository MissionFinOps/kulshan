"""Rich terminal reporter with colored tables, charts, and htop-style bars."""
from __future__ import annotations

import plotext as plt
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.text import Text
from rich.columns import Columns
from rich.rule import Rule
from rich import box
import pandas as pd
import numpy as np
from datetime import datetime

console = Console()

# ─── Sparkline characters ────────────────────────────────────────────────────
SPARK_CHARS = "▁▂▃▄▅▆▇█"


def _sparkline(values: list[float], width: int = 60) -> Text:
    """Create a colored sparkline from a list of values.
    Color per character: red=increase >10%, green=decrease >10%, dim=stable.
    Uses max-pooling when resampling to preserve spikes."""
    if not values or len(values) < 2:
        return Text("-", style="dim")

    # Max-pool resample to fit width, preserves spikes instead of skipping data
    if len(values) > width:
        bucket_size = len(values) / width
        resampled = []
        for i in range(width):
            start = int(i * bucket_size)
            end = int((i + 1) * bucket_size)
            bucket = values[start:end]
            resampled.append(max(bucket) if bucket else 0)
        values = resampled

    mn, mx = min(values), max(values)
    rng = mx - mn if mx != mn else 1.0

    spark = Text()
    for i, v in enumerate(values):
        idx = int((v - mn) / rng * (len(SPARK_CHARS) - 1))
        idx = max(0, min(idx, len(SPARK_CHARS) - 1))
        char = SPARK_CHARS[idx]

        if i == 0:
            spark.append(char, style="dim")
        elif v > values[i - 1] * 1.10:
            spark.append(char, style="red")
        elif v < values[i - 1] * 0.90:
            spark.append(char, style="green")
        else:
            spark.append(char, style="dim")

    return spark


def _format_cost(amount: float) -> str:
    """Smart cost formatting: $1.2M, $3.4K, $56.78"""
    if abs(amount) >= 1_000_000:
        return f"${amount / 1_000_000:,.1f}M"
    elif abs(amount) >= 10_000:
        return f"${amount / 1_000:,.1f}K"
    elif abs(amount) >= 1_000:
        return f"${amount:,.0f}"
    else:
        return f"${amount:,.2f}"


def _mask_account(account_id: str) -> str:
    """Mask account ID: 123456789012 → XXX...89012"""
    s = str(account_id)
    if len(s) >= 5:
        return f"XXX...{s[-5:]}"
    return s

# ─── Severity / color helpers ────────────────────────────────────────────────

def _severity_color(severity: str) -> str:
    return {
        "critical": "bold red",
        "warning": "yellow",
        "info": "blue",
        "normal": "green",
    }.get(severity, "white")


def _severity_emoji(severity: str) -> str:
    return {"critical": "🔴", "warning": "🟡", "info": "🔵"}.get(severity, "🟢")


def _bar(value: float, max_val: float, width: int = 30) -> Text:
    """Create an htop-style colored bar."""
    if max_val == 0:
        return Text("░" * width, style="dim")
    ratio = min(value / max_val, 1.0)
    filled = int(ratio * width)
    bar = Text()
    if ratio > 0.8:
        bar.append("█" * filled, style="bold red")
    elif ratio > 0.5:
        bar.append("█" * filled, style="yellow")
    else:
        bar.append("█" * filled, style="green")
    bar.append("░" * (width - filled), style="dim")
    return bar


def _trend_indicator(value: float) -> str:
    """Return a colored trend arrow."""
    if value > 20:
        return f"[bold red]▲ {value:+.1f}%[/bold red]"
    elif value > 5:
        return f"[red]↑ {value:+.1f}%[/red]"
    elif value > -5:
        return f"[white]→ {value:+.1f}%[/white]"
    elif value > -20:
        return f"[green]↓ {value:+.1f}%[/green]"
    else:
        return f"[bold green]▼ {value:+.1f}%[/bold green]"


# ─── Banner & Header ─────────────────────────────────────────────────────────

BANNER = """[bold cyan]
╔═══════════════════════════════════════════════════════════════════════════╗
║                                                                           ║
║           MF COST ANALYZER                                                ║
║           Advanced Statistical Analysis + Stunning Visualizations         ║
║                                                                           ║
╚═══════════════════════════════════════════════════════════════════════════╝[/bold cyan]"""


def print_banner():
    console.print(BANNER)


def print_header(title: str, days: int):
    console.print()
    console.print(Panel(
        f"[bold cyan]{title}[/bold cyan]\n"
        f"[dim]Analysis period: last {days} days | Generated: {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}[/dim]",
        box=box.DOUBLE_EDGE,
        border_style="cyan",
    ))
    console.print()


# ─── Summary Cards ────────────────────────────────────────────────────────────

def print_summary_cards(data: dict[str, pd.DataFrame], days: int):
    """Print summary cards at the top of the report."""
    svc_df = data.get("service", pd.DataFrame())
    if svc_df.empty:
        return

    total = svc_df["cost"].sum()
    daily_avg = total / max(days, 1)
    num_services = svc_df["service"].nunique() if "service" in svc_df.columns else 0

    # Compute period-over-period change
    mid = len(svc_df) // 2
    if mid > 0:
        first_half = svc_df.iloc[:mid]["cost"].sum()
        second_half = svc_df.iloc[mid:]["cost"].sum()
        period_change = ((second_half - first_half) / first_half * 100) if first_half > 0 else 0
    else:
        period_change = 0

    cards = [
        Panel(
            f"[bold cyan]${total:,.2f}[/bold cyan]\n[dim]Total Spend[/dim]",
            border_style="cyan", width=22,
        ),
        Panel(
            f"[bold cyan]${daily_avg:,.2f}[/bold cyan]\n[dim]Daily Average[/dim]",
            border_style="cyan", width=22,
        ),
        Panel(
            f"[bold cyan]{num_services}[/bold cyan]\n[dim]Active Services[/dim]",
            border_style="cyan", width=22,
        ),
        Panel(
            f"{_trend_indicator(period_change)}\n[dim]Period Trend[/dim]",
            border_style="cyan", width=22,
        ),
    ]
    console.print(Columns(cards, equal=True, expand=True))
    console.print()


def print_nonprod_advisory(account_names: dict[str, str]):
    """Detect non-production accounts by name and print advisory."""
    if not account_names:
        return
    nonprod_keywords = {"lab", "test", "dev", "sandbox", "staging", "demo", "poc", "trial"}
    nonprod = []
    for acct_id, name in account_names.items():
        name_lower = name.lower()
        if any(kw in name_lower for kw in nonprod_keywords):
            nonprod.append(name)
    if nonprod:
        names = ", ".join(nonprod[:5])
        if len(nonprod) > 5:
            names += f" +{len(nonprod) - 5} more"
        console.print(Panel(
            f"[yellow]⚠️ This report includes accounts that appear to be non-production: {names}[/yellow]\n"
            f"[dim]Consider running separate reports for prod vs non-prod for clearer cost attribution.[/dim]",
            border_style="yellow",
            box=box.ROUNDED,
        ))
        console.print()


# ─── Cost Tables ──────────────────────────────────────────────────────────────

def print_cost_table(df: pd.DataFrame, group_col: str, title: str, top_n: int = 9,
                     account_names: dict[str, str] | None = None, mask_accounts: bool = False):
    """Print a cost breakdown table with htop-style bars and sparklines."""
    if df.empty:
        console.print(f"[dim]No data for {title}[/dim]")
        return

    totals = df.groupby(group_col)["cost"].sum().sort_values(ascending=False)
    all_total = totals.sum()
    totals_top = totals.head(top_n)
    max_cost = totals_top.max() if not totals_top.empty else 0
    other_cost = all_total - totals_top.sum()
    num_other = len(totals) - len(totals_top)

    table = Table(
        title=f"[bold]{title}[/bold]",
        box=box.ROUNDED,
        show_lines=False,
        title_style="bold magenta",
        header_style="bold cyan",
    )
    table.add_column("#", style="dim", width=4)
    table.add_column(group_col.replace("_", " ").title(), min_width=30)
    table.add_column("Cost (USD)", justify="right", min_width=12)
    table.add_column("% Total", justify="right", min_width=8)
    table.add_column("Trend", min_width=12)
    table.add_column("Distribution", min_width=32)

    for i, (name, cost) in enumerate(totals_top.items(), 1):
        pct = cost / all_total * 100 if all_total > 0 else 0
        label = str(name)
        if account_names and group_col == "account" and str(name) in account_names:
            acct_name = account_names[str(name)]
            acct_id = _mask_account(str(name)) if mask_accounts else str(name)
            label = f"{acct_name} ({acct_id})"
        elif mask_accounts and group_col == "account":
            label = _mask_account(str(name))

        # Build sparkline from daily data for this group
        grp = df[df[group_col] == name].sort_values("date")
        spark = _sparkline(grp["cost"].tolist()) if len(grp) > 1 else Text("-", style="dim")

        table.add_row(
            str(i),
            label,
            _format_cost(cost),
            f"{pct:.1f}%",
            spark,
            _bar(cost, max_cost),
        )

    # Add "Other" row if there are truncated items
    if num_other > 0 and other_cost > 0.01:
        other_pct = other_cost / all_total * 100 if all_total > 0 else 0
        table.add_row(
            "",
            f"[dim]Other ({num_other} more)[/dim]",
            f"[dim]{_format_cost(other_cost)}[/dim]",
            f"[dim]{other_pct:.1f}%[/dim]",
            Text("", style="dim"),
            Text("", style="dim"),
        )

    table.add_section()
    table.add_row("", "[bold]TOTAL[/bold]", f"[bold]{_format_cost(all_total)}[/bold]", "100%", "", "")
    console.print(table)
    console.print()


# ─── Anomaly Detection ────────────────────────────────────────────────────────

def print_anomalies(df: pd.DataFrame, group_col: str):
    """Print multi-method anomaly detection results with severity breakdown."""
    if df.empty:
        console.print("[green]✓ No cost anomalies detected[/green]\n")
        return

    # Summary counts
    critical = len(df[df["severity"] == "critical"]) if "severity" in df.columns else 0
    warning = len(df[df["severity"] == "warning"]) if "severity" in df.columns else 0
    info = len(df[df["severity"] == "info"]) if "severity" in df.columns else 0

    console.print(Panel(
        f"[bold]🚨 ANOMALIES DETECTED: {len(df)}[/bold]\n"
        f"[red]🔴 CRITICAL: {critical}[/red]  [yellow]🟡 WARNING: {warning}[/yellow]  [blue]🔵 INFO: {info}[/blue]",
        border_style="red",
    ))

    table = Table(
        title="[bold]⚠ Cost Anomalies (Multi-Method Detection)[/bold]",
        box=box.ROUNDED,
        title_style="bold red",
        header_style="bold cyan",
    )
    table.add_column("#", style="dim", width=4)
    table.add_column(group_col.replace("_", " ").title(), min_width=25)
    table.add_column("Cost", justify="right")
    table.add_column("Average", justify="right")
    table.add_column("Deviation", justify="right")
    table.add_column("Score", justify="right")
    table.add_column("Methods")
    table.add_column("Direction")
    table.add_column("Severity")

    for i, (_, row) in enumerate(df.head(20).iterrows(), 1):
        severity = row.get("severity", "info")
        sev_style = _severity_color(severity)
        emoji = _severity_emoji(severity)
        pct = row.get("pct_change", 0)
        pct_style = "red" if pct > 0 else "green"
        score = row.get("score", row.get("z_score", 0))
        direction = "[red]↑ Spike[/red]" if pct > 0 else "[green]↓ Drop[/green]"

        table.add_row(
            str(i),
            str(row[group_col])[:45],
            f"${row['latest_cost']:,.2f}",
            f"${row['avg_cost']:,.2f}",
            f"[{pct_style}]{pct:+.1f}%[/{pct_style}]",
            f"{score:.1f}σ",
            str(row.get("methods", "")),
            direction,
            f"[{sev_style}]{emoji} {severity.upper()}[/{sev_style}]",
        )

    console.print(table)
    console.print()


# ─── Trends ───────────────────────────────────────────────────────────────────

def print_trends(df: pd.DataFrame, group_col: str):
    """Print growth trend table with colored indicators."""
    if df.empty:
        console.print("[dim]No trend data available[/dim]\n")
        return

    table = Table(
        title="[bold]📈 Cost Trends[/bold]",
        box=box.ROUNDED,
        title_style="bold blue",
        header_style="bold cyan",
    )
    table.add_column(group_col.replace("_", " ").title(), min_width=25)
    table.add_column("Total Cost", justify="right")
    table.add_column("Daily Avg", justify="right")
    table.add_column("WoW", justify="right")
    table.add_column("MoM", justify="right")

    for _, row in df.head(9).iterrows():
        table.add_row(
            str(row[group_col]),
            f"${row['total_cost']:,.2f}",
            f"${row['daily_avg']:,.2f}",
            _trend_indicator(row["wow_growth_pct"]),
            _trend_indicator(row["mom_growth_pct"]),
        )

    console.print(table)
    console.print()


def print_top_movers(df: pd.DataFrame, group_col: str):
    """Print top cost movers."""
    if df.empty:
        return

    table = Table(
        title="[bold]🔄 Top Cost Movers (Week over Week)[/bold]",
        box=box.ROUNDED,
        title_style="bold yellow",
        header_style="bold cyan",
    )
    table.add_column(group_col.replace("_", " ").title(), min_width=25)
    table.add_column("This Week", justify="right")
    table.add_column("Last Week", justify="right")
    table.add_column("Change", justify="right")
    table.add_column("", width=3)

    for _, row in df.iterrows():
        chg_style = "red" if row["absolute_change"] > 0 else "green"
        table.add_row(
            str(row[group_col]),
            f"${row['latest_week']:,.2f}",
            f"${row['previous_week']:,.2f}",
            f"[{chg_style}]${row['absolute_change']:+,.2f}[/{chg_style}]",
            row["direction"],
        )

    console.print(table)
    console.print()


# ─── Waste / Idle / Pareto ────────────────────────────────────────────────────

def print_idle_resources(df: pd.DataFrame, group_col: str):
    """Print potentially idle resources."""
    if df.empty:
        console.print("[green]✓ No idle resources detected[/green]\n")
        return

    table = Table(
        title="[bold]💤 Potentially Idle Resources[/bold]",
        box=box.ROUNDED,
        title_style="bold yellow",
        header_style="bold cyan",
    )
    table.add_column(group_col.replace("_", " ").title(), min_width=25)
    table.add_column("Daily Avg", justify="right")
    table.add_column("Total", justify="right")
    table.add_column("Days", justify="right")
    table.add_column("Recommendation")

    for _, row in df.iterrows():
        table.add_row(
            str(row[group_col]),
            f"${row['daily_avg_cost']:.4f}",
            f"${row['total_cost']:,.2f}",
            str(row["days_active"]),
            f"[yellow]{row['recommendation']}[/yellow]",
        )

    console.print(table)
    console.print()


def print_pareto(df: pd.DataFrame, group_col: str):
    """Print Pareto (80/20) analysis."""
    if df.empty:
        return

    table = Table(
        title="[bold]📊 Cost Distribution (Pareto Analysis)[/bold]",
        box=box.ROUNDED,
        title_style="bold magenta",
        header_style="bold cyan",
    )
    table.add_column(group_col.replace("_", " ").title(), min_width=25)
    table.add_column("Cost", justify="right")
    table.add_column("% of Total", justify="right")
    table.add_column("Cumulative %", justify="right")
    table.add_column("Group")

    for _, row in df.head(20).iterrows():
        grp_style = "red" if row["pareto_group"] == "Top 80%" else "dim"
        table.add_row(
            str(row[group_col]),
            f"${row['cost']:,.2f}",
            f"{row['pct_of_total']:.1f}%",
            f"{row['cumulative_pct']:.1f}%",
            f"[{grp_style}]{row['pareto_group']}[/{grp_style}]",
        )

    console.print(table)
    console.print()


# ─── Forecast / Coverage ─────────────────────────────────────────────────────

def print_forecast(df: pd.DataFrame):
    """Print cost forecast with confidence bands."""
    if df.empty:
        console.print("[dim]Forecast not available (need 14+ days of history)[/dim]\n")
        return

    total_forecast = df["forecast"].sum()
    daily_avg = df["forecast"].mean()

    lines = [
        f"[bold]Forecasted spend (next {len(df)} days):[/bold] [cyan]${total_forecast:,.2f}[/cyan]",
        f"[bold]Forecasted daily average:[/bold] [cyan]${daily_avg:,.2f}[/cyan]",
    ]

    # Confidence bands if available
    if "lower_bound" in df.columns and "upper_bound" in df.columns:
        total_lower = df["lower_bound"].sum()
        total_upper = df["upper_bound"].sum()
        if total_lower != total_forecast or total_upper != total_forecast:
            lines.append("")
            lines.append(f"[bold]80% Confidence Range:[/bold]")
            lines.append(f"  [green]Low:  ${total_lower:,.2f}[/green]  →  "
                         f"[cyan]Expected: ${total_forecast:,.2f}[/cyan]  →  "
                         f"[red]High: ${total_upper:,.2f}[/red]")
            spread = total_upper - total_lower
            lines.append(f"  [dim]Spread: ${spread:,.2f} (±${spread / 2:,.2f})[/dim]")

    console.print(Panel(
        "\n".join(lines),
        title="[bold]🔮 Cost Forecast[/bold]",
        border_style="blue",
    ))
    console.print()


def print_coverage(ri_df: pd.DataFrame, sp_df: pd.DataFrame):
    """Print RI/SP coverage and utilization."""
    panels = []
    if not sp_df.empty:
        for _, row in sp_df.iterrows():
            util = row["utilization_pct"]
            style = "green" if util > 80 else ("yellow" if util > 50 else "red")
            panels.append(Panel(
                f"Utilization: [{style}]{util:.1f}%[/{style}]\n"
                f"Commitment: ${row['total_commitment']:,.2f}\n"
                f"Used: ${row['used_commitment']:,.2f}\n"
                f"Unused: [red]${row['unused_commitment']:,.2f}[/red]",
                title="Savings Plans",
                border_style="blue",
            ))

    if panels:
        console.print(Columns(panels))
        console.print()

    if not ri_df.empty:
        print_cost_table_generic(ri_df, "service", "coverage_pct", "RI Coverage by Service")


def print_cost_table_generic(df: pd.DataFrame, label_col: str, value_col: str, title: str):
    """Generic table printer."""
    table = Table(title=f"[bold]{title}[/bold]", box=box.ROUNDED, header_style="bold cyan")
    table.add_column(label_col.title(), min_width=25)
    table.add_column(value_col.replace("_", " ").title(), justify="right")

    for _, row in df.iterrows():
        table.add_row(str(row[label_col]), f"{row[value_col]:.1f}%")

    console.print(table)
    console.print()


# ─── Recommendations ──────────────────────────────────────────────────────────

def print_recommendations(anomalies_df: pd.DataFrame, idle_df: pd.DataFrame,
                          ri_df: pd.DataFrame, sp_df: pd.DataFrame,
                          data: dict | None = None, network_data: dict | None = None):
    """Print data-driven, prioritized recommendations citing actual analysis results."""
    recs = []
    savings_estimates = []

    # ── Anomaly-driven recs ───────────────────────────────────────────
    if not anomalies_df.empty and "severity" in anomalies_df.columns:
        critical = anomalies_df[anomalies_df["severity"] == "critical"]
        if len(critical) > 0:
            top_a = critical.iloc[0]
            group_col = anomalies_df.columns[0]
            recs.append("[red]🔴 INVESTIGATE ANOMALIES:[/red]")
            recs.append(f"   • {len(critical)} critical anomalies detected")
            recs.append(f"   • Highest: {top_a[group_col]} at ${top_a['latest_cost']:,.2f} "
                        f"({top_a.get('pct_change', 0):+.1f}% vs avg ${top_a['avg_cost']:,.2f})")
            recs.append(f"   • Action: Check CloudTrail for {top_a[group_col]} API activity")
            recs.append("")

    # ── Commitment-driven recs ────────────────────────────────────────
    if data and not data.get("purchase_option", pd.DataFrame()).empty:
        po = data["purchase_option"]
        od = po[po["purchase_option"].str.contains("On Demand", case=False, na=False)]
        if not od.empty:
            od_total = od["cost"].sum()
            total = po["cost"].sum()
            od_pct = od_total / total * 100 if total > 0 else 0
            if od_pct > 50:
                est_savings = od_total * 0.30  # ~30% savings with SP/RI
                recs.append("[cyan]💰 PURCHASE SAVINGS PLANS / RESERVED INSTANCES:[/cyan]")
                recs.append(f"   • {od_pct:.0f}% of spend (${od_total:,.0f}) is On-Demand")
                if data and not data.get("instance_type", pd.DataFrame()).empty:
                    top_inst = data["instance_type"].groupby("instance_type")["cost"].sum().sort_values(ascending=False)
                    top_inst = top_inst[top_inst.index != "NoInstanceType"].head(2)
                    if not top_inst.empty:
                        inst_names = ", ".join(f"{n} (${c:,.0f})" for n, c in top_inst.items())
                        recs.append(f"   • Top instance types: {inst_names}")
                recs.append(f"   • Est. savings with 1-year Compute SP: ~{_format_cost(est_savings)}/period")
                recs.append(f"   • Action: `aws ce get-savings-plans-purchase-recommendation`")
                savings_estimates.append(est_savings)
                recs.append("")

    # ── Idle resource recs ────────────────────────────────────────────
    if not idle_df.empty:
        idle_total = idle_df["total_cost"].sum() if "total_cost" in idle_df.columns else 0
        top_idle = idle_df.iloc[0] if len(idle_df) > 0 else None
        group_col = idle_df.columns[0]
        recs.append("[yellow]💤 ELIMINATE IDLE RESOURCES:[/yellow]")
        recs.append(f"   • {len(idle_df)} idle services detected, total waste: {_format_cost(idle_total)}")
        if top_idle is not None:
            recs.append(f"   • Largest: {top_idle[group_col]} at ${top_idle.get('daily_avg_cost', 0):.2f}/day")
        recs.append(f"   • Action: Review and terminate unused resources")
        savings_estimates.append(idle_total)
        recs.append("")

    # ── SP utilization recs ───────────────────────────────────────────
    if not sp_df.empty:
        for _, row in sp_df.iterrows():
            unused = row.get("unused_commitment", 0)
            if unused > 0:
                recs.append("[blue]📊 OPTIMIZE SAVINGS PLAN UTILIZATION:[/blue]")
                recs.append(f"   • Unused commitment: ${unused:,.2f} "
                            f"(utilization: {row.get('utilization_pct', 0):.1f}%)")
                recs.append(f"   • Action: Align workloads to maximize SP coverage")
                recs.append("")
                break

    # ── Network recs ──────────────────────────────────────────────────
    if network_data and network_data.get("categories"):
        cats = network_data["categories"]
        net_total = network_data["grand_total"]
        if net_total > 500:
            recs.append("[blue]🌐 OPTIMIZE NETWORK COSTS:[/blue]")
            recs.append(f"   • Total network spend: {_format_cost(net_total)}")
            if "nat_gateway" in cats and cats["nat_gateway"]["total"] > 100:
                nat_cost = cats["nat_gateway"]["total"]
                recs.append(f"   • NAT Gateway: {_format_cost(nat_cost)}, replace with VPC Endpoints for S3/DynamoDB")
                savings_estimates.append(nat_cost * 0.3)
            if "data_transfer_out" in cats and cats["data_transfer_out"]["total"] > 500:
                recs.append(f"   • Internet egress: {_format_cost(cats['data_transfer_out']['total'])}, consider CloudFront caching")
            recs.append("")

    # ── Summary ───────────────────────────────────────────────────────
    if savings_estimates:
        total_potential = sum(savings_estimates)
        recs.append(f"[bold green]💎 TOTAL ESTIMATED SAVINGS POTENTIAL: {_format_cost(total_potential)}[/bold green]")

    if not recs:
        recs.append("[green]✓ No critical issues found. Your cost posture looks healthy.[/green]")

    console.print(Panel(
        "\n".join(recs),
        title="[bold]📋 DATA-DRIVEN RECOMMENDATIONS[/bold]",
        border_style="green",
        box=box.DOUBLE_EDGE,
    ))
    console.print()


# ─── WoW Insights ─────────────────────────────────────────────────────────────

def print_wow_insights(insights: dict):
    """Print WoW (Week-over-Week) insights panel."""
    if not insights:
        return

    trend_emoji = {"increasing": "📈", "decreasing": "📉", "stable": "➡️"}.get(insights["trend"], "➡️")
    trend_color = {"increasing": "red", "decreasing": "green", "stable": "white"}.get(insights["trend"], "white")

    lines = []
    lines.append(f"[bold]Overall Trend:[/bold] [{trend_color}]{trend_emoji} {insights['trend'].title()}[/{trend_color}]")
    lines.append("")

    if "most_expensive_day" in insights:
        d = insights["most_expensive_day"]
        lines.append(f"[red]💸 Most Expensive Day:[/red] {d['date']}, {_format_cost(d['cost'])}")
    if "least_expensive_day" in insights:
        d = insights["least_expensive_day"]
        lines.append(f"[green]💰 Least Expensive Day:[/green] {d['date']}, {_format_cost(d['cost'])}")

    lines.append("")
    lines.append(f"[bold]Day-of-Week Pattern:[/bold]")

    # Sparkline of day-of-week averages
    dow_costs = [cost for _, cost in insights.get("dow_pattern", [])]
    if dow_costs:
        dow_spark = _sparkline(dow_costs, width=7)
        dow_labels = "  ".join([day[:3] for day, _ in insights["dow_pattern"]])
        lines.append(f"  {dow_labels}")

    lines.append(f"  Most expensive: [red]{insights.get('most_expensive_dow', '-')}[/red]")
    lines.append(f"  Least expensive: [green]{insights.get('least_expensive_dow', '-')}[/green]")
    lines.append(f"  Weekday avg: {_format_cost(insights.get('weekday_avg', 0))} | Weekend avg: {_format_cost(insights.get('weekend_avg', 0))}")

    lines.append("")
    wow_pct = insights.get("wow_change_pct", 0)
    wow_style = "red" if wow_pct > 0 else "green"
    lines.append(f"[bold]Week-over-Week:[/bold] [{wow_style}]{wow_pct:+.1f}%[/{wow_style}]")
    lines.append(f"  This week: {_format_cost(insights.get('current_week_total', 0))} | Last week: {_format_cost(insights.get('previous_week_total', 0))}")

    console.print(Panel(
        "\n".join(lines),
        title="[bold]🔍 Cost Insights (WoW Analysis)[/bold]",
        border_style="magenta",
    ))
    console.print()


# ─── Rightsizing Recommendations ──────────────────────────────────────────────

def print_rightsizing(df: pd.DataFrame):
    """Print AWS rightsizing recommendations."""
    if df.empty:
        console.print("[dim]No rightsizing recommendations available (requires ce:GetRightsizingRecommendation)[/dim]\n")
        return

    total_savings = df["estimated_savings"].sum()

    console.print(Panel(
        f"[bold]{len(df)} recommendations found[/bold] | "
        f"Potential monthly savings: [green]{_format_cost(total_savings)}[/green]",
        title="[bold]🔧 AWS Rightsizing Recommendations[/bold]",
        border_style="green",
    ))

    table = Table(box=box.ROUNDED, header_style="bold cyan")
    table.add_column("#", style="dim", width=4)
    table.add_column("Instance", min_width=15)
    table.add_column("Current Type", min_width=12)
    table.add_column("Action")
    table.add_column("Target Type", min_width=12)
    table.add_column("Current Cost", justify="right")
    table.add_column("New Cost", justify="right")
    table.add_column("Savings/mo", justify="right")

    for i, (_, row) in enumerate(df.head(15).iterrows(), 1):
        action_style = "yellow" if row["action"] == "MODIFY" else "red"
        table.add_row(
            str(i),
            str(row.get("instance_id", "-"))[:20],
            str(row.get("instance_type", "-")),
            f"[{action_style}]{row['action']}[/{action_style}]",
            str(row.get("target_type", "-")),
            _format_cost(row.get("monthly_cost", 0)),
            _format_cost(row.get("target_monthly_cost", 0)),
            f"[green]{_format_cost(row.get('estimated_savings', 0))}[/green]",
        )

    console.print(table)
    console.print()


# ─── Cost Story ────────────────────────────────────────────────────────────────

def print_cost_story(story: str):
    """Print the natural language cost summary as a prominent panel."""
    if not story:
        return
    console.print(Panel(
        f"[white]{story}[/white]",
        title="[bold]📖 Cost Story[/bold]",
        border_style="cyan",
        box=box.ROUNDED,
        padding=(1, 2),
    ))
    console.print()


# ─── Charts ───────────────────────────────────────────────────────────────────

def plot_daily_costs(df: pd.DataFrame):
    """Plot daily cost trend using plotext (terminal chart)."""
    if df.empty or len(df) < 2:
        return

    plt.clear_figure()
    plt.date_form("Y-m-d")
    dates = [d.strftime("%Y-%m-%d") for d in df["date"]]
    plt.plot(dates, df["cost"].tolist(), label="Daily Cost", marker="braille", color="cyan")
    if "7d_avg" in df.columns:
        plt.plot(dates, df["7d_avg"].tolist(), label="7-day Avg", marker="braille", color="yellow")
    plt.title("Daily Cost Trend")
    plt.xlabel("Date")
    plt.ylabel("Cost (USD)")
    plt.theme("dark")
    plt.plotsize(100, 20)
    plt.show()
    print()


def plot_service_breakdown(df: pd.DataFrame, group_col: str, top_n: int = 10):
    """Plot horizontal bar chart of top services."""
    if df.empty:
        return

    totals = df.groupby(group_col)["cost"].sum().sort_values(ascending=True).tail(top_n)

    plt.clear_figure()
    plt.simple_bar(
        [str(s)[:30] for s in totals.index],
        totals.values.tolist(),
        title=f"Top {top_n} by Cost",
        color="cyan",
        width=100,
    )
    plt.show()
    print()


# ─── Cost Efficiency Score ─────────────────────────────────────────────────────

def print_efficiency_score(score_data: dict):
    """Print the cost efficiency score panel."""
    if not score_data:
        return

    total = score_data["total_score"]
    grade = score_data["grade"]
    grade_color = {"A": "bold green", "B": "green", "C": "yellow", "D": "red", "F": "bold red"}.get(grade, "white")

    lines = [f"[{grade_color}]Score: {total}/100 (Grade: {grade})[/{grade_color}]", ""]

    for key, item in score_data.get("breakdown", {}).items():
        label = key.replace("_", " ").title()
        lines.append(
            f"  {item['status']}  {label:.<25s} {item['score']:>5.1f}/{item['max']}  "
            f"({item['value']}, target: {item['target']})"
        )

    # Top recommendation
    lines.append("")
    worst = min(score_data.get("breakdown", {}).values(), key=lambda x: x["score"] / x["max"], default=None)
    if worst:
        worst_name = [k for k, v in score_data["breakdown"].items() if v is worst][0]
        lines.append(f"[cyan]🎯 Focus area: {worst_name.replace('_', ' ').title()}, currently {worst['value']}[/cyan]")

    console.print(Panel(
        "\n".join(lines),
        title=f"[bold]🏆 Cost Efficiency Score: {total}/100[/bold]",
        border_style=grade_color.replace("bold ", ""),
    ))
    console.print()


# ─── Network Deep-Dive ────────────────────────────────────────────────────────

def print_network_breakdown(network_data: dict, total_spend: float):
    """Print network cost deep-dive."""
    if not network_data or not network_data.get("categories"):
        console.print("[dim]No network cost data available[/dim]\n")
        return

    grand = network_data["grand_total"]
    net_pct = (grand / total_spend * 100) if total_spend > 0 else 0

    table = Table(
        title=f"[bold]🌐 Network Cost Deep-Dive, {_format_cost(grand)} ({net_pct:.1f}% of total)[/bold]",
        box=box.ROUNDED,
        title_style="bold blue",
        header_style="bold cyan",
    )
    table.add_column("Category", min_width=25)
    table.add_column("Cost", justify="right", min_width=12)
    table.add_column("% Network", justify="right")
    table.add_column("Distribution", min_width=30)

    from ..analyzers.network import get_category_label
    max_cost = max((c["total"] for c in network_data["categories"].values()), default=0)

    for key, cat in network_data["categories"].items():
        table.add_row(
            get_category_label(key),
            _format_cost(cat["total"]),
            f"{cat['pct']:.1f}%",
            _bar(cat["total"], max_cost, width=25),
        )

    table.add_section()
    table.add_row("[bold]TOTAL[/bold]", f"[bold]{_format_cost(grand)}[/bold]", "100%", "")
    console.print(table)

    # Optimization hints
    cats = network_data["categories"]
    hints = []
    if "nat_gateway" in cats and cats["nat_gateway"]["total"] > 100:
        hints.append("💡 Replace NAT Gateways with VPC Endpoints for S3/DynamoDB to reduce data processing charges")
    if "data_transfer_out" in cats and cats["data_transfer_out"]["total"] > 500:
        hints.append("💡 Review internet egress, consider CloudFront caching for static content")
    if "data_transfer_inter_region" in cats and cats["data_transfer_inter_region"]["total"] > 500:
        hints.append("💡 High inter-region transfer, consider regional data caching or architecture changes")

    if hints:
        console.print(Panel(
            "\n".join(hints),
            title="[bold]🔧 Network Optimization[/bold]",
            border_style="blue",
            box=box.ROUNDED,
        ))
    console.print()


# ─── Interactive Menu ─────────────────────────────────────────────────────────

def interactive_service_menu(services: list[tuple[str, float]]) -> str | None:
    """Display interactive service selection menu. Returns service name or None for all."""
    if not services:
        return None

    console.print(Panel(
        f"[bold]{len(services)} services found[/bold]",
        title="[bold]Service Filter[/bold]",
        border_style="cyan",
    ))

    table = Table(box=box.SIMPLE, header_style="bold cyan", show_edge=False)
    table.add_column("#", style="dim", width=4)
    table.add_column("Service", min_width=45)
    table.add_column("Cost (7d)", justify="right")

    for i, (svc, cost) in enumerate(services[:15], 1):
        table.add_row(str(i), svc[:50], f"${cost:,.2f}")

    if len(services) > 15:
        table.add_row("", f"[dim]... and {len(services) - 15} more[/dim]", "")

    console.print(table)
    console.print("\n[dim]Enter number to filter by service, or press Enter for ALL[/dim]")

    return None  # Actual input handled in CLI


def interactive_period_menu() -> int:
    """Display period selection. Returns days."""
    console.print(Panel(
        "[bold]1)[/bold] 7 days    [bold]2)[/bold] 30 days    [bold]3)[/bold] 60 days\n"
        "[bold]4)[/bold] 90 days [cyan][DEFAULT][/cyan]    [bold]5)[/bold] 180 days    [bold]6)[/bold] 365 days",
        title="[bold]Analysis Period[/bold]",
        border_style="cyan",
    ))
    return 90  # Default, actual input handled in CLI


def interactive_sensitivity_menu() -> float:
    """Display sensitivity selection. Returns threshold."""
    console.print(Panel(
        "[bold]1)[/bold] High (1.5σ)    [bold]2)[/bold] Medium (2.0σ) [cyan][DEFAULT][/cyan]    [bold]3)[/bold] Low (3.0σ)",
        title="[bold]Anomaly Detection Sensitivity[/bold]",
        border_style="cyan",
    ))
    return 2.0  # Default, actual input handled in CLI


# ─── Sprint 2: New display functions ──────────────────────────────────────────

def print_cost_comparison(df: pd.DataFrame):
    """Print period-over-period cost comparison."""
    if df.empty:
        console.print("[dim]No comparison data available[/dim]\n")
        return

    table = Table(
        title="[bold]🔄 Period-over-Period Cost Comparison[/bold]",
        box=box.ROUNDED, title_style="bold blue", header_style="bold cyan",
    )
    table.add_column("Service", min_width=30)
    table.add_column("Current", justify="right")
    table.add_column("Previous", justify="right")
    table.add_column("Change", justify="right")
    table.add_column("% Change", justify="right")

    for _, row in df.head(9).iterrows():
        chg = row["difference"]
        pct = row["pct_change"]
        style = "red" if chg > 0 else "green"
        arrow = "↑" if chg > 0 else "↓"
        table.add_row(
            str(row["service"])[:45],
            _format_cost(row["current"]),
            _format_cost(row["baseline"]),
            f"[{style}]{arrow} {_format_cost(abs(chg))}[/{style}]",
            f"[{style}]{pct:+.1f}%[/{style}]",
        )

    console.print(table)
    console.print()


def print_cost_drivers(df: pd.DataFrame):
    """Print cost change drivers."""
    if df.empty:
        console.print("[dim]No cost driver data available[/dim]\n")
        return

    table = Table(
        title="[bold]🔍 What's Driving Cost Changes?[/bold]",
        box=box.ROUNDED, title_style="bold magenta", header_style="bold cyan",
    )
    table.add_column("Driver", min_width=30)
    table.add_column("Category")
    table.add_column("Impact", justify="right")
    table.add_column("Description", min_width=30)

    for _, row in df.head(9).iterrows():
        impact = row["impact"]
        style = "red" if impact > 0 else "green"
        table.add_row(
            str(row["driver"])[:40],
            str(row["category"]),
            f"[{style}]{_format_cost(impact)}[/{style}]",
            str(row["description"])[:50],
        )

    console.print(table)
    console.print()


def print_sp_recommendation(rec: dict):
    """Print Savings Plans purchase recommendation."""
    if not rec or not rec.get("details"):
        console.print("[dim]No Savings Plans recommendations available[/dim]\n")
        return

    lines = [
        f"[bold]Type:[/bold] {rec.get('sp_type', '-')} | "
        f"[bold]Term:[/bold] {rec.get('term', '-')} | "
        f"[bold]Payment:[/bold] {rec.get('payment', '-')}",
        "",
        f"[bold green]Estimated Monthly Savings: {_format_cost(rec.get('estimated_monthly_savings', 0))}[/bold green]",
        f"[bold]Savings Percentage:[/bold] {rec.get('estimated_savings_pct', 0):.1f}%",
        f"[bold]Hourly Commitment:[/bold] ${rec.get('hourly_commitment', 0):.4f}/hr",
    ]

    console.print(Panel("\n".join(lines), title="[bold]💰 Savings Plans Purchase Recommendation[/bold]", border_style="green"))

    if rec.get("details"):
        table = Table(box=box.ROUNDED, header_style="bold cyan")
        table.add_column("Account")
        table.add_column("Hourly Commit", justify="right")
        table.add_column("Current OD", justify="right")
        table.add_column("Est. Savings %", justify="right")
        table.add_column("Monthly Savings", justify="right")

        for d in rec["details"]:
            table.add_row(
                str(d["account"]),
                f"${d['hourly_commitment']:.4f}",
                f"${d['current_on_demand']:.4f}",
                f"{d['estimated_savings_pct']:.1f}%",
                f"[green]{_format_cost(d['estimated_monthly_savings'])}[/green]",
            )
        console.print(table)
    console.print()


def print_ri_recommendation(rec: dict):
    """Print Reserved Instance purchase recommendation."""
    if not rec or not rec.get("details"):
        console.print("[dim]No RI recommendations available[/dim]\n")
        return

    console.print(Panel(
        f"[bold]Service:[/bold] {rec.get('service', '-')} | "
        f"[bold]Term:[/bold] {rec.get('term', '-')} | "
        f"[bold]Payment:[/bold] {rec.get('payment', '-')}\n\n"
        f"[bold green]Total Monthly Savings: {_format_cost(rec.get('total_monthly_savings', 0))}[/bold green]",
        title="[bold]📊 Reserved Instance Purchase Recommendation[/bold]",
        border_style="blue",
    ))

    if rec.get("details"):
        table = Table(box=box.ROUNDED, header_style="bold cyan")
        table.add_column("Instance Type")
        table.add_column("Region")
        table.add_column("Count", justify="right")
        table.add_column("Upfront", justify="right")
        table.add_column("Monthly", justify="right")
        table.add_column("Savings/mo", justify="right")

        for d in rec["details"]:
            table.add_row(
                d["instance_type"],
                d["region"],
                str(d["recommended_count"]),
                _format_cost(d["upfront_cost"]),
                _format_cost(d["monthly_cost"]),
                f"[green]{_format_cost(d['estimated_monthly_savings'])}[/green]",
            )
        console.print(table)
    console.print()


def print_aws_anomalies(df: pd.DataFrame):
    """Print anomalies from AWS Cost Anomaly Detection service."""
    if df.empty:
        console.print("[dim]No AWS Cost Anomaly Detection data (service may not be configured)[/dim]\n")
        return

    total_impact = df["total_impact"].sum()
    console.print(Panel(
        f"[bold]{len(df)} anomalies detected by AWS ML[/bold] | "
        f"Total impact: [red]{_format_cost(total_impact)}[/red]",
        title="[bold]🤖 AWS Cost Anomaly Detection (ML-Based)[/bold]",
        border_style="red",
    ))

    table = Table(box=box.ROUNDED, header_style="bold cyan")
    table.add_column("Service", min_width=25)
    table.add_column("Start Date")
    table.add_column("Impact", justify="right")
    table.add_column("Actual", justify="right")
    table.add_column("Expected", justify="right")
    table.add_column("Region")
    table.add_column("Usage Type")

    for _, row in df.head(9).iterrows():
        table.add_row(
            str(row["service"])[:35],
            str(row["start_date"])[:10],
            f"[red]{_format_cost(row['total_impact'])}[/red]",
            _format_cost(row["total_actual"]),
            _format_cost(row["total_expected"]),
            str(row.get("region", ""))[:15],
            str(row.get("usage_type", ""))[:25],
        )

    console.print(table)
    console.print()


# ─── Tag Breakdown ────────────────────────────────────────────────────────────

def print_tag_breakdown(df: pd.DataFrame, tag_key: str):
    """Print cost breakdown by tag value."""
    if df.empty:
        console.print(f"[yellow]No data for tag '{tag_key}'. Ensure the tag is activated as a cost allocation tag.[/yellow]\n")
        return

    totals = df.groupby("tag_value")["cost"].sum().sort_values(ascending=False).head(9)
    all_total = totals.sum()
    max_cost = totals.max() if not totals.empty else 0

    table = Table(
        title=f"[bold]🏷️ Cost by Tag: {tag_key}[/bold]",
        box=box.ROUNDED, title_style="bold blue", header_style="bold cyan",
    )
    table.add_column("#", style="dim", width=4)
    table.add_column("Tag Value", min_width=25)
    table.add_column("Cost", justify="right")
    table.add_column("% Total", justify="right")
    table.add_column("Distribution", min_width=25)

    for i, (val, cost) in enumerate(totals.items(), 1):
        pct = cost / all_total * 100 if all_total > 0 else 0
        table.add_row(str(i), str(val), _format_cost(cost), f"{pct:.1f}%", _bar(cost, max_cost, width=20))

    table.add_section()
    table.add_row("", "[bold]TOTAL[/bold]", f"[bold]{_format_cost(all_total)}[/bold]", "100%", "")
    console.print(table)
    console.print()

def print_marketplace(df: pd.DataFrame, account_names: dict[str, str] | None = None):
    """Print AWS Marketplace (3rd-party vendor) spend by account and service."""
    if df.empty:
        console.print("[dim]No AWS Marketplace spend detected.[/dim]\n")
        return

    account_names = account_names or {}

    # Pivot: rows = (account, service), columns = months
    pivot = df.pivot_table(index=["account", "service"], columns="month", values="cost", aggfunc="sum", fill_value=0)
    pivot["total"] = pivot.sum(axis=1)
    pivot = pivot.sort_values("total", ascending=False)
    months = [c for c in pivot.columns if c != "total"]

    table = Table(
        title="[bold]🛒 AWS Marketplace Spend[/bold]",
        box=box.ROUNDED, title_style="bold blue", header_style="bold cyan",
    )
    table.add_column("Account", min_width=18)
    table.add_column("Marketplace Item", min_width=25)
    for m in months:
        table.add_column(m, justify="right", min_width=10)
    table.add_column("Total", justify="right", style="bold")

    grand_total = 0
    for (acct, svc), row in pivot.iterrows():
        acct_label = account_names.get(acct, acct)
        month_vals = [_format_cost(row[m]) if row[m] > 0 else "[dim]-[/dim]" for m in months]
        total = row["total"]
        grand_total += total
        table.add_row(acct_label, svc, *month_vals, _format_cost(total))

    table.add_section()
    table.add_row("[bold]TOTAL[/bold]", "", *["" for _ in months], f"[bold]{_format_cost(grand_total)}[/bold]")
    console.print(table)
    console.print(f"  [dim]{len(pivot)} marketplace items across {df['account'].nunique()} accounts[/dim]\n")




# ─── EC2-Other Breakdown ──────────────────────────────────────────────────────

def print_ec2_breakdown(df: pd.DataFrame):
    """Print EC2-Other cost breakdown by usage type."""
    if df.empty:
        console.print("[dim]No EC2-Other cost data[/dim]\n")
        return

    total = df["cost"].sum()
    max_cost = df["cost"].max()

    table = Table(
        title=f"[bold]🖥️ EC2-Other Breakdown, {_format_cost(total)}[/bold]",
        box=box.ROUNDED, title_style="bold yellow", header_style="bold cyan",
    )
    table.add_column("#", style="dim", width=4)
    table.add_column("Usage Type", min_width=35)
    table.add_column("Cost", justify="right")
    table.add_column("% Total", justify="right")
    table.add_column("Distribution", min_width=20)

    for i, (_, row) in enumerate(df.head(15).iterrows(), 1):
        pct = row["cost"] / total * 100 if total > 0 else 0
        # Friendly name from usage type
        ut = str(row["usage_type"])
        if ":" in ut:
            ut = ut.split(":", 1)[1]  # Strip region prefix
        table.add_row(str(i), ut[:45], _format_cost(row["cost"]), f"{pct:.1f}%", _bar(row["cost"], max_cost, width=15))

    table.add_section()
    table.add_row("", "[bold]TOTAL[/bold]", f"[bold]{_format_cost(total)}[/bold]", "100%", "")
    console.print(table)
    console.print()


# ─── Top Resources ────────────────────────────────────────────────────────────

def print_top_resources(df: pd.DataFrame):
    """Print top most expensive individual resources."""
    if df.empty:
        console.print("[dim]No resource-level data (requires EC2 resource-level opt-in in Billing console)[/dim]\n")
        return

    total = df["cost"].sum()
    table = Table(
        title=f"[bold]💎 Top {len(df)} Most Expensive Resources, {_format_cost(total)}[/bold]",
        box=box.ROUNDED, title_style="bold red", header_style="bold cyan",
    )
    table.add_column("#", style="dim", width=4)
    table.add_column("Resource ID", min_width=25)
    table.add_column("Cost (14d)", justify="right")

    for i, (_, row) in enumerate(df.iterrows(), 1):
        table.add_row(str(i), str(row["resource_id"]), _format_cost(row["cost"]))

    console.print(table)
    console.print()


# ─── Cost Heatmap ─────────────────────────────────────────────────────────────

def print_cost_heatmap(df: pd.DataFrame):
    """Print a day-of-week cost heatmap (GitHub contribution style)."""
    if df.empty:
        console.print("[dim]No data for heatmap[/dim]\n")
        return

    daily = df.groupby("date")["cost"].sum().reset_index().sort_values("date")
    if len(daily) < 7:
        return

    daily["dow"] = daily["date"].dt.dayofweek  # 0=Mon, 6=Sun
    daily["week"] = daily["date"].dt.isocalendar().week.astype(int)
    daily["year"] = daily["date"].dt.year

    max_cost = daily["cost"].max()
    if max_cost == 0:
        return

    HEAT = " ░▒▓█"
    COLORS = ["dim", "green", "yellow", "rgb(255,165,0)", "bold red"]

    # Build week columns
    weeks = daily.groupby(["year", "week"]).first().reset_index().sort_values("date")
    week_keys = list(zip(weeks["year"], weeks["week"]))[-12:]  # Last 12 weeks

    dow_names = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]

    lines = ["[bold]📅 Cost Heatmap (last 12 weeks)[/bold]", ""]
    header = "     " + "".join(f" W{w[1]:02d}" for w in week_keys)
    lines.append(f"[dim]{header}[/dim]")

    for dow in range(7):
        row_text = Text(f" {dow_names[dow]}  ")
        for yw in week_keys:
            cell = daily[(daily["year"] == yw[0]) & (daily["week"] == yw[1]) & (daily["dow"] == dow)]
            if cell.empty:
                row_text.append("  ·  ", style="dim")
            else:
                cost = cell["cost"].values[0]
                intensity = min(4, int(cost / max_cost * 4))
                char = HEAT[intensity]
                style = COLORS[intensity]
                row_text.append(f"  {char}  ", style=style)
        lines.append("")
        console.print(row_text)

    console.print(f"\n[dim]  · = no data  ░ = low  ▒ = medium  ▓ = high  █ = peak[/dim]")
    console.print()


# ─── Executive Summary ────────────────────────────────────────────────────────

def print_executive_summary(
    data: dict, days: int, anomalies_df, insights: dict,
    efficiency_score: dict | None, forecast_df, story: str,
):
    """Print a compact one-page executive summary."""
    svc_df = data.get("service", pd.DataFrame())
    if svc_df.empty:
        console.print("[dim]No data for summary[/dim]")
        return

    total = svc_df["cost"].sum()
    daily_avg = total / max(days, 1)
    num_svc = svc_df["service"].nunique()

    lines = []
    lines.append(f"[bold cyan]Total Spend:[/bold cyan] {_format_cost(total)} over {days} days ({_format_cost(daily_avg)}/day)")
    lines.append("")

    # Top 3 services
    top3 = svc_df.groupby("service")["cost"].sum().sort_values(ascending=False).head(3)
    lines.append("[bold]Top 3 Services:[/bold]")
    for i, (name, cost) in enumerate(top3.items(), 1):
        pct = cost / total * 100 if total > 0 else 0
        lines.append(f"  {i}. {name}: {_format_cost(cost)} ({pct:.0f}%)")
    lines.append("")

    # Trend
    if insights:
        trend = insights.get("trend", "stable")
        wow = insights.get("wow_change_pct", 0)
        emoji = {"increasing": "📈", "decreasing": "📉", "stable": "➡️"}.get(trend, "➡️")
        lines.append(f"[bold]Trend:[/bold] {emoji} {trend.title()} ({wow:+.1f}% WoW)")

    # Anomalies
    if anomalies_df is not None and not anomalies_df.empty:
        n = len(anomalies_df)
        crit = len(anomalies_df[anomalies_df["severity"] == "critical"]) if "severity" in anomalies_df.columns else 0
        lines.append(f"[bold]Anomalies:[/bold] {n} detected ({crit} critical)")
    else:
        lines.append("[bold]Anomalies:[/bold] None detected ✓")

    # Efficiency
    if efficiency_score:
        lines.append(f"[bold]Efficiency Score:[/bold] {efficiency_score['total_score']}/100 (Grade: {efficiency_score['grade']})")

    # Forecast
    if forecast_df is not None and not forecast_df.empty:
        fc_total = forecast_df["forecast"].sum()
        lines.append(f"[bold]30-Day Forecast:[/bold] {_format_cost(fc_total)}")

    lines.append("")
    if story:
        lines.append(f"[dim]{story}[/dim]")

    console.print(Panel(
        "\n".join(lines),
        title=f"[bold]📋 Executive Summary, {days} Days[/bold]",
        border_style="cyan",
        box=box.DOUBLE_EDGE,
        padding=(1, 2),
    ))
    console.print()


# ─── WOW Features ─────────────────────────────────────────────────────────────

import time as _time


def print_cold_open(data: dict, days: int):
    """Cinematic one-liner before full analysis loads."""
    svc_df = data.get("service", pd.DataFrame())
    if svc_df.empty:
        return

    total = svc_df["cost"].sum()
    po_df = data.get("purchase_option", pd.DataFrame())
    od_pct = 100.0
    if not po_df.empty:
        od = po_df[po_df["purchase_option"].str.contains("On Demand", case=False, na=False)]
        if not od.empty:
            od_pct = od["cost"].sum() / po_df["cost"].sum() * 100

    # Pick template based on data pattern
    if od_pct > 95:
        line = f"⚡ {_format_cost(total)} in {days} days. {od_pct:.0f}% On-Demand. Zero commitments. Let's fix that."
    elif total > 100000:
        line = f"⚡ {_format_cost(total)} in {days} days. That's {_format_cost(total / max(days, 1))}/day walking out the door."
    else:
        line = f"⚡ {_format_cost(total)} in {days} days. Here's where every dollar went."

    console.print(f"\n[bold cyan]{line}[/bold cyan]\n")


def print_cost_in_human_terms(total_spend: float, days: int, savings: float = 0):
    """Translate AWS spend into relatable human terms."""
    if total_spend <= 0:
        return

    monthly = total_spend / max(days, 1) * 30
    per_day = total_spend / max(days, 1)
    per_hour = per_day / 24
    per_min = per_hour / 60

    comparisons = [
        ("🏠", "median US home mortgage payments", monthly / 5667),
        ("👩‍💻", "senior engineer salaries", monthly / 15000),
        ("🚗", "Toyota Camrys per year", (monthly * 12) / 28000),
        ("☕", "Starbucks lattes", monthly / 5.50),
    ]

    lines = [f"[bold]💰 Your AWS Spend in Human Terms:[/bold]", f"  {_format_cost(monthly)}/month ="]
    for emoji, label, count in comparisons:
        if count >= 0.1:
            lines.append(f"    {emoji} {count:.1f} {label}")

    lines.append(f"    🔥 {_format_cost(per_day)}/day = {_format_cost(per_hour)}/hour = {_format_cost(per_min)}/minute")
    lines.append(f"    [dim]While you read this analysis (~2 min), you spent {_format_cost(per_min * 2)} on AWS.[/dim]")

    if savings > 0:
        eng_equiv = savings / 12 / 15000
        lines.append(f"\n  [green]Your potential savings ({_format_cost(savings)}/yr) = {eng_equiv:.1f} additional engineers[/green]")

    console.print(Panel("\n".join(lines), border_style="cyan", box=box.ROUNDED))
    console.print()


SERVICE_ECOSYSTEMS = {
    "EC2 Ecosystem": [
        "Amazon Elastic Compute Cloud - Compute", "EC2 - Other",
        "Amazon Elastic Block Store", "Amazon EBS",
    ],
    "Networking": [
        "Amazon Virtual Private Cloud", "AWS Cloud WAN", "AWS Network Firewall",
        "Amazon Route 53", "Amazon CloudFront", "AWS Transit Gateway",
        "Elastic Load Balancing", "Amazon Elastic Load Balancing",
    ],
    "Data & Analytics": [
        "Amazon OpenSearch Service", "Amazon QuickSight", "Amazon Athena",
        "AWS Glue", "Amazon Kinesis", "Amazon Redshift",
    ],
    "Database": [
        "Amazon Relational Database Service", "Amazon DynamoDB",
        "Amazon ElastiCache", "Amazon Neptune", "Amazon DocumentDB",
    ],
    "Containers": [
        "Amazon Elastic Container Service", "Amazon Elastic Container Service for Kubernetes",
        "Amazon ECR", "Amazon EC2 Container Registry (ECR)", "AWS Fargate",
    ],
    "Security & Compliance": [
        "AWS WAF", "Amazon GuardDuty", "AWS Security Hub", "Amazon Inspector",
        "Amazon Macie", "AWS Key Management Service", "AWS CloudTrail",
    ],
    "Management & Monitoring": [
        "AmazonCloudWatch", "AWS Systems Manager", "AWS Config",
        "Amazon Managed Grafana", "AWS Cost Explorer",
    ],
}


def print_service_ecosystems(df: pd.DataFrame):
    """Group services into ecosystems and show true workload costs."""
    if df.empty:
        return

    totals = df.groupby("service")["cost"].sum()
    grand_total = totals.sum()
    if grand_total <= 0:
        return

    eco_results = []
    mapped_services = set()

    for eco_name, services in SERVICE_ECOSYSTEMS.items():
        eco_cost = sum(totals.get(s, 0) for s in services)
        if eco_cost > 0.01:
            members = [(s, totals.get(s, 0)) for s in services if totals.get(s, 0) > 0.01]
            members.sort(key=lambda x: x[1], reverse=True)
            eco_results.append((eco_name, eco_cost, members))
            mapped_services.update(s for s, _ in members)

    # Unmapped services
    other_cost = sum(c for s, c in totals.items() if s not in mapped_services and c > 0.01)
    if other_cost > 0.01:
        eco_results.append(("Other Services", other_cost, []))

    eco_results.sort(key=lambda x: x[1], reverse=True)

    lines = []
    for eco_name, eco_cost, members in eco_results[:6]:
        pct = eco_cost / grand_total * 100
        lines.append(f"[bold]{eco_name}: {_format_cost(eco_cost)} ({pct:.0f}%)[/bold]")
        for svc, cost in members[:4]:
            svc_short = svc.replace("Amazon ", "").replace("AWS ", "")[:35]
            lines.append(f"  ├── {svc_short}: {_format_cost(cost)}")
        lines.append("")

    console.print(Panel(
        "\n".join(lines),
        title="[bold]🏗️ Service Ecosystem Map[/bold]",
        border_style="blue", box=box.ROUNDED,
    ))
    console.print()


def generate_tldr(data: dict, days: int, anomalies_df=None, score_data=None, insights=None) -> str:
    """Generate 280-char tweetable summary."""
    svc_df = data.get("service", pd.DataFrame())
    if svc_df.empty:
        return ""

    total = svc_df["cost"].sum()
    parts = [f"📊 AWS {days}d: {_format_cost(total)}"]

    if insights and insights.get("wow_change_pct"):
        parts.append(f"({insights['wow_change_pct']:+.0f}% WoW)")

    if score_data:
        parts.append(f"| Score: {score_data['total_score']}/100 ({score_data['grade']})")

    po_df = data.get("purchase_option", pd.DataFrame())
    if not po_df.empty:
        od = po_df[po_df["purchase_option"].str.contains("On Demand", case=False, na=False)]
        if not od.empty:
            od_pct = od["cost"].sum() / po_df["cost"].sum() * 100
            if od_pct > 90:
                parts.append(f"| {od_pct:.0f}% On-Demand 😬")

    if anomalies_df is not None and not anomalies_df.empty:
        parts.append(f"| {len(anomalies_df)} anomalies")

    top_svc = svc_df.groupby("service")["cost"].sum().idxmax()
    top_svc_short = top_svc.replace("Amazon ", "").replace("AWS ", "")[:20]
    parts.append(f"| Top: {top_svc_short}")

    result = " ".join(parts)
    return result[:280]


def print_tldr(tldr: str):
    """Print tweetable summary."""
    if not tldr:
        return
    console.print(Panel(tldr, title="[bold]🐦 TL;DR (280 chars)[/bold]", border_style="cyan"))
    console.print()


def print_slot_machine_score(score_data: dict):
    """Animated efficiency score reveal."""
    if not score_data:
        return
    from rich.live import Live

    final_score = score_data["total_score"]
    grade = score_data["grade"]

    try:
        with Live(console=console, refresh_per_second=30) as live:
            for i in range(0, final_score + 1):
                color = "green" if i >= 80 else ("yellow" if i >= 50 else "red")
                live.update(Panel(
                    f"[bold {color}]{i}[/bold {color}]",
                    title="[bold]🏆 Efficiency Score[/bold]",
                    border_style=color, width=30,
                ))
                _time.sleep(max(0.01, 0.12 * (i / max(final_score, 1)) ** 2))

        console.print(f"  [bold]Grade: {grade}[/bold]\n")
    except Exception:
        # Fallback if Live doesn't work (piped output, etc.)
        print_efficiency_score(score_data)


def print_cost_dna(df: pd.DataFrame, account_names: dict = None):
    """Classify accounts into behavioral archetypes."""
    if df.empty or "account" not in df.columns:
        return

    archetypes = {
        "steady": ("🏔️", "Steady Mountain", "High, stable spend"),
        "roller": ("🎢", "Roller Coaster", "High variance, spiky"),
        "ghost": ("👻", "Ghost Town", "Minimal activity"),
        "rocket": ("🚀", "Growth Rocket", "Rapidly increasing"),
        "sunset": ("📉", "Sunset", "Declining, decommission candidate?"),
    }

    lines = []
    for acct, group in df.groupby("account"):
        daily = group.groupby("date")["cost"].sum()
        if len(daily) < 7:
            continue

        mean = daily.mean()
        std = daily.std()
        cv = std / mean if mean > 0 else 0

        # Trend slope
        x = np.arange(len(daily))
        slope = np.polyfit(x, daily.values, 1)[0] if len(x) > 1 else 0
        trend_pct = (slope * len(daily)) / mean * 100 if mean > 0 else 0

        # Classify
        if mean < 1.0:
            arch = "ghost"
        elif trend_pct > 20:
            arch = "rocket"
        elif trend_pct < -15:
            arch = "sunset"
        elif cv > 0.5:
            arch = "roller"
        else:
            arch = "steady"

        emoji, name, desc = archetypes[arch]
        acct_label = account_names.get(str(acct), str(acct)) if account_names else str(acct)
        lines.append(f"  {emoji} {acct_label:.<40s} [bold]{name}[/bold], {desc}")

    if lines:
        console.print(Panel(
            "\n".join(lines),
            title="[bold]🧬 Account Behavioral DNA[/bold]",
            border_style="magenta", box=box.ROUNDED,
        ))
        console.print()


def print_tide_charts(df: pd.DataFrame):
    """Show day-of-week spend rhythm with today's comparison."""
    if df.empty:
        return

    daily = df.groupby("date")["cost"].sum().reset_index().sort_values("date")
    if len(daily) < 14:
        return

    daily["dow"] = daily["date"].dt.dayofweek
    daily["dow_name"] = daily["date"].dt.day_name()

    dow_stats = daily.groupby("dow")["cost"].agg(["mean", "std"]).reset_index()
    dow_names = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    max_avg = dow_stats["mean"].max()

    lines = ["[bold]🌊 Weekly Spend Rhythm:[/bold]", ""]
    for _, row in dow_stats.iterrows():
        dow = int(row["dow"])
        avg = row["mean"]
        bar_len = int(avg / max_avg * 20) if max_avg > 0 else 0
        bar = "█" * bar_len + "░" * (20 - bar_len)
        style = "red" if avg == max_avg else ("green" if avg == dow_stats["mean"].min() else "white")
        label = "  (peak)" if avg == max_avg else ("  (low)" if avg == dow_stats["mean"].min() else "")
        lines.append(f"  {dow_names[dow]}  [{style}]{bar}[/{style}]  {_format_cost(avg)}{label}")

    # Today's comparison
    today_dow = datetime.utcnow().weekday()
    today_avg = dow_stats[dow_stats["dow"] == today_dow]["mean"].values
    if len(today_avg) > 0 and len(daily) > 0:
        latest = daily.iloc[-1]["cost"]
        pct_vs_dow = ((latest - today_avg[0]) / today_avg[0] * 100) if today_avg[0] > 0 else 0
        lines.append(f"\n  [bold]Today ({dow_names[today_dow]}): {_format_cost(latest)}, {pct_vs_dow:+.0f}% vs {dow_names[today_dow]} average[/bold]")

    console.print(Panel("\n".join(lines), border_style="blue", box=box.ROUNDED))
    console.print()


def print_burndown(total_spend: float, days: int, budget: float, period: str = "annual"):
    """Budget burn rate countdown."""
    if budget <= 0 or total_spend <= 0:
        return

    daily_rate = total_spend / max(days, 1)
    period_days = {"annual": 365, "quarterly": 90, "monthly": 30}.get(period, 365)

    today = datetime.utcnow()
    if period == "annual":
        period_start = today.replace(month=1, day=1)
        period_end = today.replace(month=12, day=31)
    elif period == "quarterly":
        q_start_month = ((today.month - 1) // 3) * 3 + 1
        period_start = today.replace(month=q_start_month, day=1)
        period_end = period_start + pd.DateOffset(months=3) - pd.DateOffset(days=1)
    else:
        period_start = today.replace(day=1)
        period_end = (period_start + pd.DateOffset(months=1)) - pd.DateOffset(days=1)

    days_elapsed = (today - pd.Timestamp(period_start)).days
    ytd_spend = daily_rate * days_elapsed
    remaining = budget - ytd_spend
    pct_consumed = ytd_spend / budget * 100

    if daily_rate > 0:
        days_until_exhausted = remaining / daily_rate
        exhaustion_date = today + pd.DateOffset(days=int(days_until_exhausted))
    else:
        exhaustion_date = period_end
        days_until_exhausted = 999

    bar_len = min(30, int(pct_consumed / 100 * 30))
    bar = "█" * bar_len + "░" * (30 - bar_len)
    bar_color = "green" if pct_consumed < 70 else ("yellow" if pct_consumed < 90 else "red")

    lines = [
        f"[bold]{period.title()} Budget:[/bold] {_format_cost(budget)}",
        f"[bold]Spent to Date:[/bold] {_format_cost(ytd_spend)} ({days_elapsed} days)",
        f"[bold]Daily Burn Rate:[/bold] {_format_cost(daily_rate)}",
        f"",
        f"  [{bar_color}]{bar}[/{bar_color}] {pct_consumed:.1f}% consumed",
        f"",
    ]

    if exhaustion_date < pd.Timestamp(period_end):
        days_early = (pd.Timestamp(period_end) - exhaustion_date).days
        lines.append(f"[red]📅 Budget exhausted: {exhaustion_date.strftime('%B %d, %Y')}[/red]")
        lines.append(f"[red]⚠️  That's {days_early} days BEFORE {period} end[/red]")
        target_rate = remaining / max((pd.Timestamp(period_end) - pd.Timestamp(today)).days, 1)
        reduction = ((daily_rate - target_rate) / daily_rate * 100)
        lines.append(f"\n  To stay within budget: reduce daily spend to {_format_cost(target_rate)} (-{reduction:.1f}%)")
    else:
        lines.append(f"[green]✅ On track, budget lasts until {exhaustion_date.strftime('%B %d, %Y')}[/green]")

    lines.append(f"\n  ⏰ Days until budget crisis: {int(days_until_exhausted)}")

    console.print(Panel(
        "\n".join(lines),
        title=f"[bold]🌡️ Budget Burn Rate ({period.title()})[/bold]",
        border_style="yellow", box=box.ROUNDED,
    ))
    console.print()


# ─── WOW Features ─────────────────────────────────────────────────────────────

def print_cold_open(text: str):
    """Print the cinematic cold open one-liner."""
    if text:
        console.print(f"\n[bold cyan]{text}[/bold cyan]\n")


def print_human_terms(terms: list[dict], total: float, days: int):
    """Print cost in relatable human terms."""
    if not terms:
        return
    lines = [f"[bold]💰 Your AWS Spend in Human Terms[/bold] ({_format_cost(total)} over {days} days):", ""]
    for t in terms:
        if t["ratio"] > 0:
            lines.append(f"  {t['emoji']}  {t['ratio']:.1f} {t['label']}")
        else:
            lines.append(f"  {t['emoji']}  {t['label']}")
    lines.append(f"\n  [dim]While you read this analysis (~2 min), you spent ~${total / max(days, 1) / 720:.2f} on AWS.[/dim]")
    console.print(Panel("\n".join(lines), border_style="cyan", box=box.ROUNDED))
    console.print()


def print_ecosystem_map(ecosystems: list[dict]):
    """Print service ecosystem grouping."""
    if not ecosystems:
        return
    console.print(Panel("[bold]🏗️ Service Ecosystem Map[/bold]", border_style="blue"))
    for eco in ecosystems:
        tree_lines = [f"[bold]{eco['ecosystem']}:[/bold] {_format_cost(eco['total'])} ({eco['pct']:.1f}%)"]
        for i, m in enumerate(eco["members"][:5]):
            prefix = "└──" if i == len(eco["members"][:5]) - 1 else "├──"
            pct = m["cost"] / eco["total"] * 100 if eco["total"] > 0 else 0
            svc_short = m["service"].replace("Amazon ", "").replace("AWS ", "")[:35]
            tree_lines.append(f"  {prefix} {svc_short}: {_format_cost(m['cost'])} ({pct:.0f}%)")
        if len(eco["members"]) > 5:
            tree_lines.append(f"  └── ... and {len(eco['members']) - 5} more")
        console.print("\n".join(tree_lines))
        console.print()


def print_cost_dna(profiles: list[dict], account_names: dict[str, str] | None = None):
    """Print account behavioral archetypes."""
    if not profiles:
        return
    table = Table(
        title="[bold]🧬 Account Cost DNA[/bold]",
        box=box.ROUNDED, title_style="bold magenta", header_style="bold cyan",
    )
    table.add_column("Account", min_width=25)
    table.add_column("Archetype")
    table.add_column("Daily Avg", justify="right")
    table.add_column("Variability", justify="right")
    table.add_column("Trend", justify="right")

    for p in profiles[:9]:
        acct_label = p["account"]
        if account_names and p["account"] in account_names:
            acct_label = f"{account_names[p['account']]} ({p['account'][-5:]})"
        trend_style = "red" if p["trend_pct"] > 10 else ("green" if p["trend_pct"] < -10 else "white")
        table.add_row(
            acct_label,
            f"{p['emoji']} {p['name']}",
            _format_cost(p["daily_avg"]),
            f"{p['cv']:.2f}",
            f"[{trend_style}]{p['trend_pct']:+.1f}%[/{trend_style}]",
        )

    console.print(table)
    console.print()


def print_tide_chart(tide: dict):
    """Print day-of-week spend rhythm."""
    if not tide or not tide.get("dow_stats"):
        return
    stats = tide["dow_stats"]
    max_mean = max(s["mean"] for s in stats.values()) if stats else 1

    lines = ["[bold]🌊 Weekly Spend Rhythm[/bold]", ""]
    for dow in range(7):
        if dow in stats:
            s = stats[dow]
            bar_len = int(s["mean"] / max_mean * 20) if max_mean > 0 else 0
            bar = "█" * bar_len + "░" * (20 - bar_len)
            style = "red" if s["mean"] == max_mean else ("green" if s["mean"] == min(x["mean"] for x in stats.values()) else "white")
            lines.append(f"  [{style}]{s['name']}  {bar}  {_format_cost(s['mean'])}[/{style}]")

    lines.append("")
    lines.append(f"  Today ({tide['today_dow_name']}): {_format_cost(tide['today_cost'])}, "
                 f"{tide['today_vs_dow']:+.1f}% vs {tide['today_dow_name']} avg, "
                 f"{tide['today_vs_overall']:+.1f}% vs overall")
    lines.append(f"  [dim]{tide['verdict']}[/dim]")

    console.print(Panel("\n".join(lines), border_style="blue", box=box.ROUNDED))
    console.print()


def print_burn_rate(burn: dict):
    """Print budget burn rate countdown."""
    if not burn:
        return
    pct = burn["pct_consumed"]
    bar_len = int(pct / 100 * 30)
    bar = "█" * min(bar_len, 30) + "░" * max(30 - bar_len, 0)
    bar_style = "green" if pct < 60 else ("yellow" if pct < 85 else "red")

    lines = [
        f"[bold]Annual Budget:[/bold]    {_format_cost(burn['budget'])}",
        f"[bold]Spent YTD (est):[/bold]  {_format_cost(burn['ytd_spend_est'])}",
        f"[bold]Daily Burn Rate:[/bold]  {_format_cost(burn['daily_rate'])}/day",
        "",
        f"  [{bar_style}]{bar}[/{bar_style}] {pct:.1f}% consumed",
        "",
    ]

    if burn["on_track"]:
        lines.append(f"[green]✅ On track, budget lasts past fiscal year end[/green]")
    else:
        lines.append(f"[red]📅 Budget exhausted: {burn['exhaustion_date']}[/red]")
        if burn["days_before_end"] > 0:
            lines.append(f"[red]⚠️  That's {burn['days_before_end']} days BEFORE fiscal year end[/red]")
        lines.append("")
        lines.append(f"[yellow]To stay within budget:[/yellow]")
        lines.append(f"  └── Reduce daily spend to {_format_cost(burn['required_daily_rate'])}/day ({burn['rate_reduction_pct']:+.1f}%)")

    console.print(Panel("\n".join(lines), title="[bold]🌡️ Budget Burn Rate[/bold]", border_style="red", box=box.ROUNDED))
    console.print()


def print_slot_machine_score(score: int, grade: str):
    """Animated efficiency score reveal (slot machine effect)."""
    import time
    from rich.live import Live

    try:
        with Live(console=console, refresh_per_second=30, transient=True) as live:
            for i in range(0, score + 1):
                color = "green" if i >= 80 else ("yellow" if i >= 50 else "red")
                live.update(Panel(
                    f"[bold {color}]{i}[/bold {color}]",
                    title="[bold]🏆 Efficiency Score[/bold]",
                    border_style=color.replace("bold ", ""),
                    width=30,
                ))
                # Slow down as we approach the final number
                delay = max(0.01, 0.12 * (i / max(score, 1)) ** 2)
                time.sleep(delay)
        # Final display with grade
        color = "green" if score >= 80 else ("yellow" if score >= 50 else "red")
        console.print(f"  [{color}]Score: {score}/100, Grade: {grade}[/{color}]\n")
    except Exception:
        # Fallback if Live doesn't work (e.g., non-interactive terminal)
        pass
