"""WOW factor features, Cold Open, Cost DNA, Tide Charts, Human Terms, Ecosystem Map, Burn Rate."""
from __future__ import annotations

import pandas as pd
import numpy as np
from datetime import datetime


# ── Service Ecosystem Mapping ─────────────────────────────────────────────

ECOSYSTEM_MAP = {
    "EC2 Ecosystem": [
        "Amazon Elastic Compute Cloud - Compute",
        "EC2 - Other",
        "Amazon Elastic Block Store",
        "Amazon Elastic Load Balancing",
    ],
    "Networking": [
        "Amazon Virtual Private Cloud",
        "AWS Cloud WAN",
        "AWS Network Firewall",
        "Amazon Route 53",
        "Amazon CloudFront",
        "AWS Transit Gateway",
    ],
    "Data & Analytics": [
        "Amazon OpenSearch Service",
        "Amazon QuickSight",
        "Amazon Athena",
        "AWS Glue",
        "Amazon Kinesis",
    ],
    "Database": [
        "Amazon Relational Database Service",
        "Amazon DynamoDB",
        "Amazon ElastiCache",
        "Amazon Redshift",
    ],
    "Containers": [
        "Amazon Elastic Container Service",
        "Amazon Elastic Container Service for Kubernetes",
        "Amazon Elastic Container Registry (ECR)",
        "AWS Fargate",
    ],
    "Security & Compliance": [
        "AWS WAF",
        "Amazon GuardDuty",
        "AWS Security Hub",
        "Amazon Inspector",
        "Amazon Macie",
        "AWS Key Management Service",
    ],
    "Management & Monitoring": [
        "AmazonCloudWatch",
        "AWS CloudTrail",
        "AWS Config",
        "AWS Systems Manager",
        "AWS Cost Explorer",
        "AWS Billing Conductor",
    ],
    "Storage": [
        "Amazon Simple Storage Service",
        "AWS Backup",
    ],
}


def compute_ecosystem_costs(df: pd.DataFrame) -> list[dict]:
    """Group services into ecosystems and compute costs."""
    if df.empty:
        return []

    svc_totals = df.groupby("service")["cost"].sum()
    grand_total = svc_totals.sum()

    ecosystems = []
    mapped_services = set()

    for eco_name, services in ECOSYSTEM_MAP.items():
        members = []
        eco_total = 0
        for svc in services:
            if svc in svc_totals.index:
                cost = svc_totals[svc]
                members.append({"service": svc, "cost": round(cost, 2)})
                eco_total += cost
                mapped_services.add(svc)

        if eco_total > 0.01:
            ecosystems.append({
                "ecosystem": eco_name,
                "total": round(eco_total, 2),
                "pct": round(eco_total / grand_total * 100, 1) if grand_total > 0 else 0,
                "members": sorted(members, key=lambda x: x["cost"], reverse=True),
            })

    # Unmapped services
    other_total = 0
    other_members = []
    for svc, cost in svc_totals.items():
        if svc not in mapped_services and cost > 0.01:
            other_members.append({"service": svc, "cost": round(cost, 2)})
            other_total += cost

    if other_total > 0.01:
        ecosystems.append({
            "ecosystem": "Other Services",
            "total": round(other_total, 2),
            "pct": round(other_total / grand_total * 100, 1) if grand_total > 0 else 0,
            "members": sorted(other_members, key=lambda x: x["cost"], reverse=True),
        })

    return sorted(ecosystems, key=lambda x: x["total"], reverse=True)


# ── Cost DNA (Account Archetypes) ─────────────────────────────────────────

ARCHETYPES = {
    "steady_mountain": ("🏔️", "Steady Mountain", "High, stable spend"),
    "roller_coaster": ("🎢", "Roller Coaster", "High variance, unpredictable"),
    "ghost_town": ("👻", "Ghost Town", "Minimal activity"),
    "growth_rocket": ("🚀", "Growth Rocket", "Rapidly increasing spend"),
    "sunset": ("📉", "Sunset", "Declining, possible decommission candidate"),
}


def compute_cost_dna(df: pd.DataFrame) -> list[dict]:
    """Classify accounts into behavioral archetypes."""
    if df.empty or "account" not in df.columns:
        return []

    results = []
    for acct, group in df.groupby("account"):
        daily = group.groupby("date")["cost"].sum().sort_values()
        costs = daily.values

        if len(costs) < 7:
            continue

        mean = np.mean(costs)
        std = np.std(costs)
        cv = std / mean if mean > 0 else 0

        # Trend slope
        x = np.arange(len(costs))
        slope = np.polyfit(x, costs, 1)[0] if len(x) > 1 else 0
        trend_pct = (slope * len(costs)) / mean * 100 if mean > 0 else 0

        # Classify
        if mean < 1.0:
            archetype = "ghost_town"
        elif trend_pct > 20:
            archetype = "growth_rocket"
        elif trend_pct < -15:
            archetype = "sunset"
        elif cv > 0.5:
            archetype = "roller_coaster"
        else:
            archetype = "steady_mountain"

        emoji, name, desc = ARCHETYPES[archetype]
        results.append({
            "account": acct,
            "archetype": archetype,
            "emoji": emoji,
            "name": name,
            "description": desc,
            "daily_avg": round(mean, 2),
            "cv": round(cv, 2),
            "trend_pct": round(trend_pct, 1),
        })

    return sorted(results, key=lambda x: x["daily_avg"], reverse=True)


# ── Tide Charts (Day-of-Week Baseline) ────────────────────────────────────

def compute_tide_chart(df: pd.DataFrame) -> dict:
    """Compute day-of-week spend rhythm and compare today against day-specific baseline."""
    if df.empty:
        return {}

    daily = df.groupby("date")["cost"].sum().reset_index().sort_values("date")
    if len(daily) < 14:
        return {}

    daily["dow"] = daily["date"].dt.dayofweek
    daily["dow_name"] = daily["date"].dt.day_name()

    dow_stats = {}
    for dow in range(7):
        subset = daily[daily["dow"] == dow]["cost"]
        if len(subset) > 0:
            dow_stats[dow] = {
                "name": ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"][dow],
                "mean": round(subset.mean(), 2),
                "std": round(subset.std(), 2) if len(subset) > 1 else 0,
                "count": len(subset),
            }

    # Today's comparison
    today = daily.iloc[-1]
    today_dow = int(today["dow"])
    today_cost = today["cost"]
    today_stats = dow_stats.get(today_dow, {})
    today_mean = today_stats.get("mean", 0)
    today_std = today_stats.get("std", 1)
    today_deviation = ((today_cost - today_mean) / today_mean * 100) if today_mean > 0 else 0

    overall_mean = daily["cost"].mean()
    overall_deviation = ((today_cost - overall_mean) / overall_mean * 100) if overall_mean > 0 else 0

    return {
        "dow_stats": dow_stats,
        "today_cost": round(today_cost, 2),
        "today_dow": today_dow,
        "today_dow_name": today_stats.get("name", ""),
        "today_vs_dow": round(today_deviation, 1),
        "today_vs_overall": round(overall_deviation, 1),
        "verdict": _tide_verdict(today_deviation, overall_deviation),
    }


def _tide_verdict(dow_dev: float, overall_dev: float) -> str:
    if abs(dow_dev) < 10:
        return "Normal for this day of the week"
    elif dow_dev > 20:
        return f"Elevated for this day (+{dow_dev:.0f}% above average)"
    elif dow_dev < -20:
        return f"Low for this day ({dow_dev:.0f}% below average)"
    else:
        return "Slightly unusual but within range"


# ── Cold Open ─────────────────────────────────────────────────────────────

def generate_cold_open(data: dict[str, pd.DataFrame]) -> str:
    """Generate a cinematic one-liner for the first 3 seconds of output."""
    svc_df = data.get("service", pd.DataFrame())
    if svc_df.empty:
        return ""

    total = svc_df["cost"].sum()
    days = svc_df["date"].nunique() if "date" in svc_df.columns else 30

    po_df = data.get("purchase_option", pd.DataFrame())
    od_pct = 100
    if not po_df.empty:
        od = po_df[po_df["purchase_option"].str.contains("On Demand", case=False, na=False)]["cost"].sum()
        od_pct = od / total * 100 if total > 0 else 100

    # Pick template based on data pattern
    if od_pct >= 95:
        return f"⚡ ${total:,.0f} in {days} days. {od_pct:.0f}% On-Demand. Zero commitments. Let's fix that."
    elif od_pct >= 50:
        return f"📊 ${total:,.0f} in {days} days. {od_pct:.0f}% still On-Demand. Room to optimize."
    else:
        return f"✅ ${total:,.0f} in {days} days. {100 - od_pct:.0f}% committed. Looking efficient."


# ── Cost in Human Terms ───────────────────────────────────────────────────

HUMAN_REFS = {
    "mortgage": ("🏠", "median US home mortgage payments", 68000 / 12),
    "engineer": ("👩‍💻", "senior software engineer salaries", 180000 / 12),
    "camry": ("🚗", "new Toyota Camrys per year", 28000 / 12),
    "latte": ("☕", "Starbucks lattes", 5.50),
}


def cost_in_human_terms(total: float, days: int) -> list[dict]:
    """Translate spend into relatable human terms."""
    monthly = total / max(days, 1) * 30
    results = []
    for key, (emoji, label, ref_monthly) in HUMAN_REFS.items():
        ratio = monthly / ref_monthly if ref_monthly > 0 else 0
        if ratio >= 0.1:
            results.append({"emoji": emoji, "label": label, "ratio": round(ratio, 1)})

    # Per-minute rate
    per_day = total / max(days, 1)
    per_hour = per_day / 24
    per_min = per_hour / 60
    results.append({"emoji": "🔥", "label": f"${per_day:,.0f}/day = ${per_hour:,.0f}/hour = ${per_min:.2f}/minute", "ratio": 0})

    return results


# ── Burn Rate Countdown ───────────────────────────────────────────────────

def compute_burn_rate(total_spend: float, days_analyzed: int, budget: float, period_days: int = 365) -> dict:
    """Calculate when budget will be exhausted at current burn rate."""
    if total_spend <= 0 or budget <= 0:
        return {}

    daily_rate = total_spend / max(days_analyzed, 1)
    days_to_exhaust = budget / daily_rate if daily_rate > 0 else float("inf")

    from datetime import timedelta
    today = datetime.utcnow().date()
    year_start = today.replace(month=1, day=1)
    days_elapsed = (today - year_start).days
    ytd_spend = daily_rate * days_elapsed  # Estimate

    exhaustion_date = year_start + timedelta(days=int(days_to_exhaust))
    period_end = year_start + timedelta(days=period_days)
    days_before_end = (period_end - exhaustion_date).days

    # Required rate to stay within budget
    remaining_days = (period_end - today).days
    remaining_budget = budget - ytd_spend
    required_rate = remaining_budget / max(remaining_days, 1)
    rate_reduction = ((daily_rate - required_rate) / daily_rate * 100) if daily_rate > 0 else 0

    return {
        "budget": budget,
        "daily_rate": round(daily_rate, 2),
        "ytd_spend_est": round(ytd_spend, 2),
        "pct_consumed": round(ytd_spend / budget * 100, 1) if budget > 0 else 0,
        "exhaustion_date": exhaustion_date.isoformat(),
        "days_before_end": days_before_end,
        "on_track": days_before_end <= 0,
        "required_daily_rate": round(required_rate, 2),
        "rate_reduction_pct": round(rate_reduction, 1),
    }
