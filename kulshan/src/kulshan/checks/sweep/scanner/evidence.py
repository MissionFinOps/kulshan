"""Conservative evidence assessments; absence of emission is never observed zero."""

from __future__ import annotations

import math
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any

from kulshan.analyze.models import CostBasis


def activity_evidence(
    cw: Any,
    namespace: str,
    metric: str,
    dimension: str,
    resource_id: str,
    days: int,
    now: datetime | None = None,
) -> dict[str, Any]:
    # Daily periods respect the 90-day hourly retention boundary and stay below
    # GetMetricStatistics' 1,440 datapoint limit. Align to closed UTC days so
    # CloudWatch's StartTime rounding cannot introduce an out-of-window bucket.
    end = (now or datetime.now(UTC)).astimezone(UTC)
    end = end.replace(hour=0, minute=0, second=0, microsecond=0)
    start = end - timedelta(days=days)
    unit = "Count" if namespace == "AWS/Lambda" else "Bytes"
    result: dict[str, Any] = {
        "unit": unit,
        "source": "cloudwatch:GetMetricStatistics",
        "namespace": namespace,
        "metric": metric,
        "statistic": "Sum",
        "period_seconds": 86400,
        "requested_start": start.isoformat(),
        "requested_end": end.isoformat(),
        "observation_timestamps": [],
        "datapoint_count": 0,
        "coverage": 0.0,
        "observed_activity": None,
        "idle": None,
        "status": "insufficient_evidence",
        "missing_data_reason": None,
        "limitation": "Sparse metrics do not prove zero usage in missing periods; "
        "zero sums describe only this metric, not removal safety.",
    }
    try:
        response = cw.get_metric_statistics(
            Namespace=namespace,
            MetricName=metric,
            Dimensions=[{"Name": dimension, "Value": resource_id}],
            StartTime=start,
            EndTime=end,
            Period=86400,
            Statistics=["Sum"],
            Unit=unit,
        )
    except Exception as exc:
        result.update(status="could_not_check", missing_data_reason=str(exc))
        return result
    if not isinstance(response, dict) or not isinstance(response.get("Datapoints"), list):
        result["missing_data_reason"] = "Malformed CloudWatch response"
        return result
    points = response["Datapoints"]
    result["datapoint_count"] = len(points)
    values: dict[datetime, float] = {}
    invalid = False
    for point in points:
        if not isinstance(point, dict):
            invalid = True
            continue
        timestamp, value = point.get("Timestamp"), point.get("Sum")
        if (
            not isinstance(timestamp, datetime)
            or timestamp.tzinfo is None
            or not start <= timestamp < end
            or isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(value)
            or value < 0
            or point.get("Unit", unit) != unit
        ):
            invalid = True
            continue
        # Each datapoint must represent a distinct aligned daily bucket.
        if (timestamp - start).total_seconds() % 86400 or timestamp in values:
            invalid = True
            continue
        values[timestamp] = value
    result["observation_timestamps"] = [ts.isoformat() for ts in sorted(values)]
    result["coverage"] = len(values) / days
    total = sum(values.values()) if values else None
    if total is not None and not math.isfinite(total):
        invalid = True
        total = None
    result["observed_activity"] = total
    if invalid:
        result["missing_data_reason"] = "Invalid, duplicate, or out-of-window datapoints"
    elif len(values) != days:
        result["missing_data_reason"] = "Missing daily observations; no emission is not zero"
    else:
        result["status"] = "confirmed_observation"
        result["idle"] = not any(values.values())
    if any(values.values()):
        result["idle"] = False
    return result


def qualify_findings(findings: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Attach review semantics at the scanner boundary, including direct consumers."""
    for finding in findings:
        finding["monthly_cost"] = None
        finding.setdefault("status", "review_candidate")
        if finding["status"] in {"could_not_check", "insufficient_evidence"}:
            finding["confidence"] = "low"
        finding.setdefault(
            "evidence",
            {
                "source": "AWS resource configuration APIs",
                "observed_activity": finding["reason"],
                "observation_period": "point_in_time",
                "observed_at": datetime.now(UTC).isoformat(),
                "completeness": "configuration_only",
                "missing_data_reason": (
                    "Historical usage, ownership and recovery dependencies unverified"
                ),
            },
        )
        finding["evidence"].setdefault(
            "missing_or_contradictory_evidence",
            ["Removal safety, ownership and recovery dependencies are unverified"],
        )
        finding["financial"] = {
            "semantics": "unknown",
            "value": None,
            "currency": None,
            "source": None,
            "reason": "No attributable billing or resource-specific regional pricing evidence",
        }
        finding["next_step"] = (
            "Review usage, owner, deployment and recovery dependencies before any change."
        )
        if finding["status"] in {"insufficient_evidence", "could_not_check"}:
            finding["cleanup_action"] = ""
        finding["cleanup_action"] = (
            "# Manual review required; reference only, never executed: "
            + finding.get("cleanup_action", "")
        )
    return findings


def attributable_billing(
    finding: dict[str, Any], evidence: dict[str, Any] | None
) -> dict[str, Any]:
    """Carry suitable existing resource billing evidence; never infer deletion savings.

    Callers must supply a resource-attributed CE/CUR amount with its accounting
    basis and actual period. Account totals and regional list prices cannot qualify.
    No new AWS queries or permissions are introduced.
    """
    unknown: dict[str, Any] = finding["financial"]
    if not isinstance(evidence, dict):
        return unknown
    if (
        evidence.get("resource_id") != finding["resource_id"]
        or evidence.get("region") != finding["region"]
        or evidence.get("source") not in {"cur_parquet", "cost_explorer"}
        or evidence.get("semantics") != "observed_billed_cost"
    ):
        return unknown
    basis = evidence.get("cost_basis")
    if isinstance(basis, CostBasis):
        basis = basis.to_dict()
    if not isinstance(basis, dict) or not basis.get("column") or not basis.get("currency"):
        return unknown
    try:
        amount = Decimal(str(evidence["value"]))
        start = datetime.fromisoformat(evidence["period_start"])
        end = datetime.fromisoformat(evidence["period_end"])
        if not amount.is_finite() or start.tzinfo is None or end.tzinfo is None or start >= end:
            return unknown
    except (KeyError, TypeError, ValueError, InvalidOperation):
        return unknown
    return {
        "semantics": "observed_billed_cost",
        "value": str(amount),
        "currency": basis["currency"],
        "cost_basis": basis,
        "source": evidence["source"],
        "period_start": start.isoformat(),
        "period_end": end.isoformat(),
        "potential_avoidable_cost": None,
        "reason": "Observed period cost is not a monthly savings or safe-removal claim",
    }
