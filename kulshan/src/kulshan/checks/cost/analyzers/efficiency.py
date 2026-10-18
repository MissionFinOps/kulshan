"""Cost Efficiency Score, composite 0-100 score based on optimization best practices."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
from platformdirs import user_data_dir


def compute_efficiency_score(
    ri_coverage: pd.DataFrame,
    sp_utilization: pd.DataFrame,
    ri_utilization: pd.DataFrame,
    idle_df: pd.DataFrame,
    anomalies_df: pd.DataFrame,
    total_spend: float,
) -> dict:
    """
    Compute a 0-100 cost efficiency score from existing analysis data.

    Scoring breakdown (100 total):
      - RI/SP Coverage:     0-25 points (target: 80%+ coverage)
      - RI/SP Utilization:  0-25 points (target: 90%+ utilization)
      - Waste Detection:    0-20 points (fewer idle resources = better)
      - Anomaly Health:     0-15 points (fewer critical anomalies = better)
      - Cost Stability:     0-15 points (low variance = predictable spend)
    """
    # Billing aggregates cannot establish resource utilization or cost stability.
    # Withhold composite scores until those inputs have independent evidence.
    breakdown = {}
    for key, frame, column, maximum in (
        ("ri_sp_coverage", ri_coverage, "coverage_pct", 25),
        ("ri_sp_utilization", sp_utilization if not sp_utilization.empty else ri_utilization,
         "utilization_pct", 25),
    ):
        measured = frame[column].dropna() if column in frame.columns else pd.Series(dtype=float)
        breakdown[key] = {
            "score": None, "max": maximum,
            "value": f"{measured.mean():.1f}%" if not measured.empty else "unknown",
            "status": "measured" if not measured.empty else "unknown",
        }
    for key, maximum in (("waste_detection", 20), ("cost_stability", 15), ("anomaly_health", 15)):
        breakdown[key] = {"score": None, "max": maximum, "value": "unknown", "status": "unknown"}
    return {
        "total_score": None, "max_score": 100, "grade": "N/A", "breakdown": breakdown,
        "status": "unavailable",
        "limitations": [
            "Billing spend and commitment ownership do not measure utilization, waste or stability."
        ],
    }


def _grade(score: float) -> str:
    if score >= 90:
        return "A"
    elif score >= 80:
        return "B"
    elif score >= 65:
        return "C"
    elif score >= 50:
        return "D"
    return "F"


# ── Score tracking over time ──────────────────────────────────────────────

SCORE_HISTORY_FILE = str(
    Path(user_data_dir("Kulshan", "missionfinops")) / "cost-analyzer-scores.json"
)


def save_score(score_data: dict, total_spend: float):
    """Append current score to local history file."""
    entry = {
        "date": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        "score": score_data["total_score"],
        "grade": score_data["grade"],
        "total_spend": round(total_spend, 2),
    }

    history = load_score_history()

    # Don't duplicate same-day entries
    if history and history[-1]["date"] == entry["date"]:
        history[-1] = entry
    else:
        history.append(entry)

    # Keep last 365 entries
    history = history[-365:]
    path = Path(SCORE_HISTORY_FILE)
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    path.write_text(json.dumps(history, indent=2), encoding="utf-8")


def load_score_history() -> list[dict]:
    """Load score history from local file."""
    path = Path(SCORE_HISTORY_FILE)
    if not path.exists():
        return []
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return []


def get_score_trend() -> dict | None:
    """Get score trend from history. Returns None if insufficient data."""
    history = load_score_history()
    if len(history) < 2:
        return None

    current = history[-1]
    previous = history[-2]
    delta = current["score"] - previous["score"]

    # Find 30-day-ago entry if available
    thirty_days_ago = None
    for entry in reversed(history):
        if entry["date"] < datetime.now(timezone.utc).replace(day=1).strftime("%Y-%m-%d"):
            thirty_days_ago = entry
            break

    return {
        "current": current,
        "previous": previous,
        "delta": delta,
        "direction": "improving" if delta > 0 else ("declining" if delta < 0 else "stable"),
        "thirty_days_ago": thirty_days_ago,
    }
