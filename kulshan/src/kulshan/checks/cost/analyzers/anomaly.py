"""
Multi-method anomaly detection for cost data.

Detection methods:
  - Z-Score (standard deviation from mean)
  - IQR (Interquartile Range outlier detection)
  - MAD (Median Absolute Deviation - robust to outliers)
  - WoW (Week-over-Week percentage change)
"""
import pandas as pd
import numpy as np


def _iqr_bounds(values: np.ndarray) -> tuple[float, float]:
    """Compute IQR-based upper/lower bounds."""
    q1 = np.percentile(values, 25)
    q3 = np.percentile(values, 75)
    iqr = q3 - q1
    return q1 - 1.5 * iqr, q3 + 1.5 * iqr


def _mad_score(value: float, values: np.ndarray) -> float:
    """Compute MAD (Median Absolute Deviation) score."""
    median = np.median(values)
    mad = np.median(np.abs(values - median))
    if mad == 0:
        return 0.0
    # 1.4826 is the consistency constant for normal distribution
    scaled_mad = mad * 1.4826
    # Guard against near-zero MAD, use relative threshold for non-trivial costs
    if scaled_mad < 0.01 and np.median(values) < 1.0:
        return 0.0
    if scaled_mad < np.median(values) * 0.001:
        return 0.0
    return (value - median) / scaled_mad


def detect_anomalies(
    df: pd.DataFrame,
    group_col: str,
    z_threshold: float = 2.0,
    min_cost: float = 1.0,
    lookback_days: int = 3,
) -> pd.DataFrame:
    """
    Multi-method anomaly detection combining Z-Score, IQR, MAD, and WoW.

    Each anomaly is scored by the number of methods that flagged it,
    giving higher confidence when multiple methods agree.
    """
    if df.empty:
        return pd.DataFrame()

    anomalies = []
    for name, group in df.groupby(group_col):
        group = group.sort_values("date")
        if len(group) < 7:
            continue

        costs = group["cost"].values
        dates = group["date"].values

        if np.sum(costs) == 0 or np.max(costs) < min_cost:
            continue

        mean = np.mean(costs[:-lookback_days]) if len(costs) > lookback_days else np.mean(costs)
        std = np.std(costs[:-lookback_days], ddof=1) if len(costs) > lookback_days + 1 else np.std(costs, ddof=1)
        median = np.median(costs)
        iqr_lower, iqr_upper = _iqr_bounds(costs[:-lookback_days] if len(costs) > lookback_days else costs)

        # Check the most recent N days
        for i in range(-min(lookback_days, len(costs)), 0):
            cost = costs[i]
            date = dates[i]

            if cost < min_cost:
                continue

            methods = []

            # Method 1: Z-Score (guard against near-zero std dev)
            z_score = 0.0
            if std > 0:
                z_score = (cost - mean) / std
                # Cap z-score: if std is tiny relative to mean, scores are unreliable
                if std < mean * 0.005:
                    z_score = 0.0
            if abs(z_score) > z_threshold:
                methods.append(f"Z:{z_score:.1f}σ")

            # Method 2: IQR
            is_iqr_outlier = cost > iqr_upper or cost < iqr_lower
            if is_iqr_outlier:
                methods.append("IQR")

            # Method 3: MAD
            mad_score = _mad_score(cost, costs[:-lookback_days] if len(costs) > lookback_days else costs)
            if abs(mad_score) > 3.5:
                methods.append(f"MAD:{mad_score:.1f}")

            # Method 4: Week-over-Week (use positive index to avoid fragile negative wrapping)
            wow_pct = 0.0
            week_ago_idx = len(costs) + i - 7
            if week_ago_idx >= 0:
                week_ago_cost = costs[week_ago_idx]
                if week_ago_cost > 0:
                    wow_pct = (cost - week_ago_cost) / week_ago_cost * 100
                    if abs(wow_pct) > 100 and cost > 10:
                        methods.append(f"WoW:{wow_pct:+.0f}%")

            if not methods:
                continue

            # Severity based on method agreement + business context
            num_methods = len(methods)
            deviation_pct = ((cost - mean) / mean * 100) if mean > 0 else 0
            score = max(abs(z_score), abs(mad_score))
            abs_delta = abs(cost - mean)
            is_drop = cost < mean

            # Business-context severity: statistical deviation + absolute impact
            # Drops are capped at "warning", they may indicate service issues, not waste
            if is_drop:
                if abs_delta > 500 and (num_methods >= 3 or score > 3):
                    severity = "warning"
                elif num_methods >= 2 or score > z_threshold:
                    severity = "info"
                else:
                    severity = "info"
            else:
                # Spikes: require meaningful absolute impact for critical
                if abs_delta > 100 and (num_methods >= 3 or score > 3):
                    severity = "critical"
                elif abs_delta > 50 and (num_methods >= 2 or score > z_threshold):
                    severity = "warning"
                else:
                    severity = "info"

            anomalies.append({
                group_col: name,
                "date": pd.Timestamp(date),
                "latest_cost": round(cost, 2),
                "previous_cost": round(costs[i - 1], 2) if abs(i) < len(costs) else 0,
                "avg_cost": round(mean, 2),
                "median_cost": round(median, 2),
                "std_dev": round(std, 2),
                "pct_change": round(deviation_pct, 1),
                "z_score": round(z_score, 2),
                "mad_score": round(mad_score, 2),
                "wow_pct": round(wow_pct, 1),
                "score": round(score, 2),
                "methods": ", ".join(methods),
                "num_methods": num_methods,
                "severity": severity,
            })

    result = pd.DataFrame(anomalies)
    if not result.empty:
        # Deduplicate: keep only the highest-scoring anomaly per service
        result = result.sort_values("score", ascending=False)
        result = result.drop_duplicates(subset=[group_col], keep="first")
        result = result.sort_values("score", ascending=False)
    return result


def detect_daily_spikes(
    df: pd.DataFrame, group_col: str, spike_multiplier: float = 2.0
) -> pd.DataFrame:
    """Detect daily cost spikes where cost > N * rolling average."""
    if df.empty:
        return pd.DataFrame()

    spikes = []
    for name, group in df.groupby(group_col):
        group = group.sort_values("date")
        if len(group) < 7:
            continue

        group = group.copy()
        group["rolling_avg"] = group["cost"].rolling(window=7, min_periods=3).mean()
        for _, row in group.iterrows():
            if pd.isna(row["rolling_avg"]) or row["rolling_avg"] < 1.0:
                continue
            if row["cost"] > row["rolling_avg"] * spike_multiplier:
                spikes.append({
                    group_col: name,
                    "date": row["date"],
                    "cost": round(row["cost"], 2),
                    "rolling_avg": round(row["rolling_avg"], 2),
                    "multiplier": round(row["cost"] / row["rolling_avg"], 1),
                })

    return pd.DataFrame(spikes)


def detect_account_anomalies(
    df: pd.DataFrame,
    z_threshold: float = 2.0,
    min_cost: float = 1.0,
    lookback_days: int = 3,
) -> pd.DataFrame:
    """
    Detect anomalies at the service+account level for deeper drill-down.
    Uses the same multi-method approach but groups by both service and account.
    Checks the last `lookback_days` for consistency with detect_anomalies().
    """
    if df.empty or "account" not in df.columns:
        return pd.DataFrame()

    anomalies = []
    for (svc, acct), group in df.groupby(["service", "account"]):
        group = group.sort_values("date")
        if len(group) < 7:
            continue

        costs = group["cost"].values
        if np.sum(costs) == 0 or np.max(costs) < min_cost:
            continue

        baseline = costs[:-lookback_days] if len(costs) > lookback_days else costs[:-1]
        if len(baseline) < 2:
            continue

        mean = np.mean(baseline)
        std = np.std(baseline, ddof=1) if len(baseline) > 2 else 0

        for i in range(-min(lookback_days, len(costs)), 0):
            cost = costs[i]
            if cost < min_cost:
                continue

            z_score = (cost - mean) / std if std > 0 else 0
            if std > 0 and std < mean * 0.005:
                z_score = 0
            mad_score_val = _mad_score(cost, baseline)

            methods = []
            if abs(z_score) > z_threshold:
                methods.append(f"Z:{z_score:.1f}σ")
            if abs(mad_score_val) > 3.5:
                methods.append(f"MAD:{mad_score_val:.1f}")

            if methods:
                anomalies.append({
                    "service": svc,
                    "account": acct,
                    "latest_cost": round(cost, 2),
                    "avg_cost": round(mean, 2),
                    "z_score": round(z_score, 2),
                    "mad_score": round(mad_score_val, 2),
                    "methods": ", ".join(methods),
                    "score": round(max(abs(z_score), abs(mad_score_val)), 2),
                })

    result = pd.DataFrame(anomalies)
    if not result.empty:
        result = result.sort_values("score", ascending=False)
    return result
