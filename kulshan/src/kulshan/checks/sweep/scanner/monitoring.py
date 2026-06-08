"""Scan for orphaned monitoring resources: empty log groups, stale alarms, unused Lambdas."""

from datetime import datetime, timezone
from typing import Dict, List, Tuple
from ..utils.aws import safe_api_call, paginate_all


def scan_monitoring(session, regions, progress=None, task_id=None) -> Tuple[List[Dict], List[str]]:
    """Find orphaned monitoring resources across all regions."""
    orphans = []
    errors = []

    for region in regions:
        # --- Empty CloudWatch Log Groups ---
        try:
            logs = session.client("logs", region_name=region)
            groups, err = paginate_all(logs, "describe_log_groups", "logGroups")
            if err:
                errors.append(f"Logs ({region}): {err}")
            else:
                for lg in groups:
                    stored_bytes = lg.get("storedBytes", 0)
                    if stored_bytes == 0:
                        created = lg.get("creationTime")
                        age_days = None
                        if created:
                            dt = datetime.fromtimestamp(created / 1000, tz=timezone.utc)
                            age_days = (datetime.now(timezone.utc) - dt).days
                        orphans.append({
                            "resource_id": lg["logGroupName"],
                            "resource_type": "CloudWatch Log Group (empty)",
                            "category": "monitoring",
                            "region": region,
                            "reason": "Zero stored bytes",
                            "age_days": age_days,
                            "monthly_cost": 0,
                            "created": datetime.fromtimestamp(created / 1000, tz=timezone.utc).isoformat() if created else None,
                            "tags": {},
                            "cleanup_action": f"aws logs delete-log-group --log-group-name '{lg['logGroupName']}' --region {region}",
                            "confidence": "medium",
                        })
        except Exception as e:
            errors.append(f"Logs ({region}): {e}")

        # --- CloudWatch Alarms in INSUFFICIENT_DATA ---
        try:
            cw = session.client("cloudwatch", region_name=region)
            alarms, err = paginate_all(cw, "describe_alarms", "MetricAlarms",
                                       StateValue="INSUFFICIENT_DATA")
            if err:
                errors.append(f"Alarms ({region}): {err}")
            else:
                for alarm in alarms:
                    updated = alarm.get("StateUpdatedTimestamp", datetime.now(timezone.utc))
                    age_days = (datetime.now(timezone.utc) - updated).days
                    if age_days >= 30:
                        # $0.10/alarm/month for standard alarms
                        orphans.append({
                            "resource_id": alarm["AlarmName"],
                            "resource_type": "CloudWatch Alarm (stale)",
                            "category": "monitoring",
                            "region": region,
                            "reason": f"INSUFFICIENT_DATA for {age_days} days",
                            "age_days": age_days,
                            "monthly_cost": 0.10,
                            "created": None,
                            "tags": {},
                            "cleanup_action": f"aws cloudwatch delete-alarms --alarm-names '{alarm['AlarmName']}' --region {region}",
                            "confidence": "medium",
                        })
        except Exception as e:
            errors.append(f"Alarms ({region}): {e}")

        # --- Lambda Functions not invoked in 90+ days ---
        try:
            lam = session.client("lambda", region_name=region)
            functions, err = paginate_all(lam, "list_functions", "Functions")
            if err:
                errors.append(f"Lambda ({region}): {err}")
            else:
                cw = session.client("cloudwatch", region_name=region)
                for fn in functions:
                    fn_name = fn["FunctionName"]
                    last_modified = fn.get("LastModified", "")
                    # Check invocations in last 90 days
                    idle = _check_lambda_idle(cw, fn_name)
                    if idle:
                        age_days = None
                        if last_modified:
                            try:
                                dt = datetime.fromisoformat(last_modified.replace("Z", "+00:00"))
                                age_days = (datetime.now(timezone.utc) - dt).days
                            except Exception:
                                pass
                        orphans.append({
                            "resource_id": fn_name,
                            "resource_type": "Lambda Function (idle)",
                            "category": "monitoring",
                            "region": region,
                            "reason": f"Zero invocations in last 90 days (runtime: {fn.get('Runtime', '?')})",
                            "age_days": age_days,
                            "monthly_cost": 0,
                            "created": last_modified or None,
                            "tags": {},
                            "cleanup_action": f"aws lambda delete-function --function-name {fn_name} --region {region}",
                            "confidence": "low",
                        })
        except Exception as e:
            errors.append(f"Lambda ({region}): {e}")

        if progress and task_id:
            progress.advance(task_id)

    return orphans, errors


def _check_lambda_idle(cw, function_name):
    """Check if a Lambda function has had zero invocations in the last 90 days."""
    try:
        end = datetime.now(timezone.utc)
        start = end.replace(month=max(1, end.month - 3) if end.month > 3 else end.month + 9,
                            year=end.year if end.month > 3 else end.year - 1)
        resp = cw.get_metric_statistics(
            Namespace="AWS/Lambda",
            MetricName="Invocations",
            Dimensions=[{"Name": "FunctionName", "Value": function_name}],
            StartTime=start, EndTime=end,
            Period=86400 * 30, Statistics=["Sum"],
        )
        datapoints = resp.get("Datapoints", [])
        if not datapoints:
            return True
        total = sum(dp.get("Sum", 0) for dp in datapoints)
        return total == 0
    except Exception:
        return False
