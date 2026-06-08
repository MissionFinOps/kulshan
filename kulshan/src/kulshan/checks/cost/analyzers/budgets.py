"""Budget governance scanner.

Checks: budget existence, alert configuration, subscriber setup,
anomaly detection monitors, and forecast-vs-budget breach detection.
"""

from datetime import datetime, timezone, timedelta
from typing import Dict, List, Tuple


def scan_budgets(session, account_id) -> Tuple[Dict, List[Dict], List[str]]:
    """Full budget governance audit.

    Returns: (stats dict, findings list, errors list)
    """
    findings = []
    errors = []
    budgets_client = session.client("budgets", region_name="us-east-1")
    ce = session.client("ce", region_name="us-east-1")

    # --- Budgets ---
    try:
        budgets_resp = budgets_client.describe_budgets(AccountId=account_id)
        budgets_list = budgets_resp.get("Budgets", [])
    except Exception as e:
        errors.append(f"Budgets: {e}")
        budgets_list = []

    budget_details = []
    for b in budgets_list:
        name = b.get("BudgetName", "?")
        budget_type = b.get("BudgetType", "?")
        time_unit = b.get("TimeUnit", "?")
        limit_amount = float(b.get("BudgetLimit", {}).get("Amount", 0))
        actual = float(b.get("CalculatedSpend", {}).get("ActualSpend", {}).get("Amount", 0))
        forecast = float(b.get("CalculatedSpend", {}).get("ForecastedSpend", {}).get("Amount", 0))

        # Get notifications
        try:
            notif_resp = budgets_client.describe_notifications_for_budget(
                AccountId=account_id, BudgetName=name)
            notifications = notif_resp.get("Notifications", [])
        except Exception:
            notifications = []

        thresholds = []
        has_subscribers = False
        for n in notifications:
            thresholds.append(n.get("Threshold", 0))
            try:
                sub_resp = budgets_client.describe_subscribers_for_notification(
                    AccountId=account_id, BudgetName=name, Notification=n)
                if sub_resp.get("Subscribers", []):
                    has_subscribers = True
            except Exception:
                pass

        util_pct = (actual / limit_amount * 100) if limit_amount > 0 else 0
        forecast_pct = (forecast / limit_amount * 100) if limit_amount > 0 else 0
        breach = forecast > limit_amount and limit_amount > 0

        budget_details.append({
            "name": name, "type": budget_type, "time_unit": time_unit,
            "limit": limit_amount, "actual": actual, "forecast": forecast,
            "util_pct": round(util_pct, 1), "forecast_pct": round(forecast_pct, 1),
            "thresholds": sorted(thresholds), "has_subscribers": has_subscribers,
            "notification_count": len(notifications), "projected_breach": breach,
        })

    # --- Anomaly Detection ---
    anomaly_monitors = 0
    anomaly_subs = 0
    try:
        mon_resp = ce.get_anomaly_monitors()
        anomaly_monitors = len(mon_resp.get("AnomalyMonitors", []))
        sub_resp = ce.get_anomaly_subscriptions()
        anomaly_subs = len(sub_resp.get("AnomalySubscriptions", []))
    except Exception as e:
        errors.append(f"Anomaly Detection: {e}")

    # --- Generate findings ---
    if not budgets_list:
        findings.append({
            "severity": "critical",
            "title": "No budgets configured",
            "detail": "Zero AWS Budgets found. Spend is completely unmonitored.",
            "recommendation": "Create monthly budgets with alerts at 50%, 80%, and 100%.",
        })

    for bd in budget_details:
        if bd["notification_count"] == 0:
            findings.append({
                "severity": "high",
                "title": f"Budget '{bd['name']}' has no alerts configured",
                "detail": "Budget exists but nobody gets notified when thresholds are crossed.",
                "recommendation": "Add notifications at 50%, 80%, and 100% thresholds.",
            })
        elif not bd["has_subscribers"]:
            findings.append({
                "severity": "high",
                "title": f"Budget '{bd['name']}' alerts have no subscribers",
                "detail": "Alerts are configured but nobody receives them.",
                "recommendation": "Add email or SNS subscribers to budget notifications.",
            })
        elif bd["thresholds"] and min(bd["thresholds"]) >= 100:
            findings.append({
                "severity": "medium",
                "title": f"Budget '{bd['name']}' only alerts at 100%+ (too late)",
                "detail": f"Thresholds: {bd['thresholds']}. You only find out after overspend.",
                "recommendation": "Add earlier thresholds at 50% and 80%.",
            })
        if bd["projected_breach"]:
            overage = bd["forecast"] - bd["limit"]
            findings.append({
                "severity": "high",
                "title": f"Budget '{bd['name']}' projected to breach (${overage:,.0f} over)",
                "detail": f"Budget: ${bd['limit']:,.0f}, Forecast: ${bd['forecast']:,.0f} ({bd['forecast_pct']:.0f}%)",
                "recommendation": "Review spend drivers or increase budget.",
            })

    if anomaly_monitors == 0:
        findings.append({
            "severity": "high",
            "title": "Cost Anomaly Detection is not configured",
            "detail": "No anomaly monitors found. Unexpected spend spikes will go unnoticed.",
            "recommendation": "Enable Cost Anomaly Detection with at least one monitor.",
        })
    elif anomaly_subs == 0:
        findings.append({
            "severity": "medium",
            "title": "Anomaly monitors exist but no alert subscriptions",
            "detail": f"{anomaly_monitors} monitor(s) but 0 subscriptions.",
            "recommendation": "Create anomaly subscriptions with email or SNS.",
        })

    stats = {
        "total_budgets": len(budgets_list),
        "budget_details": budget_details,
        "anomaly_monitors": anomaly_monitors,
        "anomaly_subscriptions": anomaly_subs,
        "budgets_with_alerts": len([b for b in budget_details if b["notification_count"] > 0]),
        "budgets_with_subscribers": len([b for b in budget_details if b["has_subscribers"]]),
        "projected_breaches": len([b for b in budget_details if b["projected_breach"]]),
    }

    return stats, findings, errors
