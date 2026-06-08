"""Trend analysis - growth rates, forecasting, seasonality detection."""
import pandas as pd
import numpy as np


def compute_growth_rates(df: pd.DataFrame, group_col: str) -> pd.DataFrame:
    """Compute week-over-week and month-over-month growth rates."""
    if df.empty:
        return pd.DataFrame()

    results = []
    for name, group in df.groupby(group_col):
        group = group.sort_values("date")
        total = group["cost"].sum()
        if total < 1.0:
            continue

        costs = group.set_index("date")["cost"].resample("W").sum()
        if len(costs) >= 2:
            wow = ((costs.iloc[-1] - costs.iloc[-2]) / costs.iloc[-2] * 100) if costs.iloc[-2] > 0 else 0
        else:
            wow = 0

        monthly = group.set_index("date")["cost"].resample("ME").sum()
        if len(monthly) >= 2:
            mom = ((monthly.iloc[-1] - monthly.iloc[-2]) / monthly.iloc[-2] * 100) if monthly.iloc[-2] > 0 else 0
        else:
            mom = 0

        results.append({
            group_col: name,
            "total_cost": round(total, 2),
            "daily_avg": round(group["cost"].mean(), 2),
            "wow_growth_pct": round(wow, 1),
            "mom_growth_pct": round(mom, 1),
        })

    result = pd.DataFrame(results)
    if not result.empty:
        result = result.sort_values("total_cost", ascending=False)
    return result


def compute_daily_trend(df: pd.DataFrame) -> pd.DataFrame:
    """Aggregate total daily cost across all groups."""
    if df.empty:
        return pd.DataFrame()
    daily = df.groupby("date")["cost"].sum().reset_index()
    daily = daily.sort_values("date")
    daily["cost"] = daily["cost"].round(2)
    daily["7d_avg"] = daily["cost"].rolling(window=7, min_periods=1).mean().round(2)
    return daily


def top_movers(df: pd.DataFrame, group_col: str, top_n: int = 9) -> pd.DataFrame:
    """Find top cost movers (biggest absolute change) over the period."""
    if df.empty:
        return pd.DataFrame()

    results = []
    for name, group in df.groupby(group_col):
        group = group.sort_values("date")
        weekly = group.set_index("date")["cost"].resample("W").sum()
        if len(weekly) < 2:
            continue
        change = weekly.iloc[-1] - weekly.iloc[-2]
        results.append({
            group_col: name,
            "latest_week": round(weekly.iloc[-1], 2),
            "previous_week": round(weekly.iloc[-2], 2),
            "absolute_change": round(change, 2),
            "direction": "↑" if change > 0 else "↓",
        })

    result = pd.DataFrame(results)
    if not result.empty:
        result = result.sort_values("absolute_change", key=abs, ascending=False).head(top_n)
    return result
