"""Waste and optimization detection for cloud resources."""
import pandas as pd


def detect_idle_services(
    df: pd.DataFrame, group_col: str, idle_threshold: float = 0.50
) -> pd.DataFrame:
    """
    Detect services with very low but non-zero spend that may be idle/forgotten.
    Flags services costing between $0.01 and $idle_threshold/day on average.
    """
    if df.empty:
        return pd.DataFrame()

    results = []
    for name, group in df.groupby(group_col):
        daily_avg = group["cost"].mean()
        total = group["cost"].sum()
        if 0.01 < daily_avg < idle_threshold:
            results.append({
                group_col: name,
                "daily_avg_cost": round(daily_avg, 4),
                "total_cost": round(total, 2),
                "days_active": len(group),
                "recommendation": "Review - possibly idle resource",
            })

    result = pd.DataFrame(results)
    if not result.empty:
        result = result.sort_values("total_cost", ascending=False)
    return result


def coverage_opportunities(ri_df: pd.DataFrame) -> pd.DataFrame:
    """Identify services with low RI/SP coverage that could benefit from commitments."""
    if ri_df.empty:
        return pd.DataFrame()

    low_cov = ri_df[
        (ri_df["coverage_pct"] < 50) & (ri_df["on_demand_hours"] > 100)
    ].copy()
    low_cov["potential_savings_pct"] = (100 - low_cov["coverage_pct"]).round(1)
    low_cov = low_cov.sort_values("on_demand_hours", ascending=False)
    return low_cov


def compute_cost_distribution(df: pd.DataFrame, group_col: str) -> pd.DataFrame:
    """
    Compute cost distribution - Pareto analysis.
    Shows what % of total cost each group represents (80/20 rule).
    """
    if df.empty:
        return pd.DataFrame()

    totals = df.groupby(group_col)["cost"].sum().reset_index()
    totals = totals.sort_values("cost", ascending=False)
    grand_total = totals["cost"].sum()
    if grand_total == 0:
        return pd.DataFrame()

    totals["pct_of_total"] = (totals["cost"] / grand_total * 100).round(2)
    totals["cumulative_pct"] = totals["pct_of_total"].cumsum().round(2)
    totals["cost"] = totals["cost"].round(2)
    totals["pareto_group"] = totals["cumulative_pct"].apply(
        lambda x: "Top 80%" if x <= 80 else "Long tail"
    )
    return totals
