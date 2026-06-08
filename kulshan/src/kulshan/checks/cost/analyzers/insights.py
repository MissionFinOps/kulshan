"""WoW Insights - day-of-week patterns, most/least expensive days, trends, cost story."""
from __future__ import annotations

import pandas as pd
import numpy as np


def compute_wow_insights(df: pd.DataFrame) -> dict:
    """
    Compute WoW (Week-over-Week) insights from daily cost data.
    Returns dict with most/least expensive days, day-of-week patterns, etc.
    """
    if df.empty:
        return {}

    daily = df.groupby("date")["cost"].sum().reset_index().sort_values("date")
    if len(daily) < 7:
        return {}

    daily["dow"] = daily["date"].dt.day_name()
    daily["dow_num"] = daily["date"].dt.dayofweek

    # Most and least expensive days (with safe guards)
    most_expensive = daily.loc[daily["cost"].idxmax()]
    positive_costs = daily[daily["cost"] > 0]
    least_expensive = daily.loc[positive_costs["cost"].idxmin()] if not positive_costs.empty else None

    # Day-of-week averages
    dow_avg = daily.groupby(["dow_num", "dow"])["cost"].mean().reset_index()
    dow_avg = dow_avg.sort_values("dow_num")
    dow_pattern = [(row["dow"], round(row["cost"], 2)) for _, row in dow_avg.iterrows()]

    # Most expensive day of week
    most_expensive_dow = dow_avg.loc[dow_avg["cost"].idxmax()]
    least_expensive_dow = dow_avg.loc[dow_avg["cost"].idxmin()]

    # Weekend vs weekday
    weekday_avg = daily[daily["dow_num"] < 5]["cost"].mean()
    weekend_avg = daily[daily["dow_num"] >= 5]["cost"].mean()

    # Current week vs previous week
    if len(daily) >= 14:
        current_week = daily.tail(7)["cost"].sum()
        previous_week = daily.iloc[-14:-7]["cost"].sum()
        wow_change = ((current_week - previous_week) / previous_week * 100) if previous_week > 0 else 0
    else:
        current_week = daily["cost"].sum()
        previous_week = 0
        wow_change = 0

    # Trend direction (linear regression slope)
    x = np.arange(len(daily))
    y = daily["cost"].values
    if len(x) > 1:
        slope = np.polyfit(x, y, 1)[0]
        trend = "increasing" if slope > 0.5 else ("decreasing" if slope < -0.5 else "stable")
    else:
        slope = 0
        trend = "stable"

    result = {
        "most_expensive_day": {
            "date": most_expensive["date"].strftime("%Y-%m-%d (%A)"),
            "cost": round(most_expensive["cost"], 2),
        },
        "dow_pattern": dow_pattern,
        "most_expensive_dow": most_expensive_dow["dow"],
        "least_expensive_dow": least_expensive_dow["dow"],
        "weekday_avg": round(weekday_avg, 2) if not pd.isna(weekday_avg) else 0,
        "weekend_avg": round(weekend_avg, 2) if not pd.isna(weekend_avg) else 0,
        "current_week_total": round(current_week, 2),
        "previous_week_total": round(previous_week, 2),
        "wow_change_pct": round(wow_change, 1),
        "trend": trend,
        "daily_slope": round(slope, 4),
    }

    if least_expensive is not None:
        result["least_expensive_day"] = {
            "date": least_expensive["date"].strftime("%Y-%m-%d (%A)"),
            "cost": round(least_expensive["cost"], 2),
        }

    return result


def _format_cost_text(amount: float) -> str:
    """Smart cost formatting for narrative text."""
    if abs(amount) >= 1_000_000:
        return f"${amount / 1_000_000:,.1f}M"
    elif abs(amount) >= 10_000:
        return f"${amount / 1_000:,.1f}K"
    elif abs(amount) >= 1_000:
        return f"${amount:,.0f}"
    else:
        return f"${amount:,.2f}"


def generate_cost_story(
    data: dict[str, pd.DataFrame],
    anomalies_df: pd.DataFrame | None = None,
    insights: dict | None = None,
) -> str:
    """Generate an executive-friendly natural language cost summary."""
    svc_df = data.get("service", pd.DataFrame())
    if svc_df.empty:
        return "No cost data available for the analyzed period."

    total = svc_df["cost"].sum()
    top_service = svc_df.groupby("service")["cost"].sum().idxmax()

    parts = [f"Over the analyzed period, your AWS spend totaled {_format_cost_text(total)}."]

    if insights:
        trend = insights.get("trend", "stable")
        wow_pct = insights.get("wow_change_pct", 0)
        if trend == "increasing":
            parts.append(f"Costs are trending upward, with a {wow_pct:+.1f}% week-over-week increase.")
        elif trend == "decreasing":
            parts.append(f"Good news, costs are trending down, with a {wow_pct:+.1f}% week-over-week decrease.")
        else:
            parts.append("Costs have been relatively stable week-over-week.")

    parts.append(f"Your highest-cost service is {top_service}.")

    if anomalies_df is not None and not anomalies_df.empty:
        sev_col = "severity" if "severity" in anomalies_df.columns else None
        if sev_col:
            critical = len(anomalies_df[anomalies_df[sev_col] == "critical"])
            if critical > 0:
                top_a = anomalies_df.iloc[0]
                svc_name = top_a.get("service", top_a.get(anomalies_df.columns[0], "Unknown"))
                parts.append(
                    f"⚠️ {critical} critical anomalies detected. "
                    f"The most significant is {svc_name} at "
                    f"{_format_cost_text(top_a['latest_cost'])} "
                    f"({top_a.get('pct_change', 0):+.1f}% vs average)."
                )
            else:
                parts.append(f"{len(anomalies_df)} minor anomalies detected, nothing critical.")
    else:
        parts.append("No cost anomalies were detected.")

    return " ".join(parts)
