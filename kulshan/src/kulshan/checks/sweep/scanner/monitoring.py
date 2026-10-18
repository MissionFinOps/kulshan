"""Scan for orphaned monitoring resources: empty log groups, stale alarms, unused Lambdas."""

from datetime import datetime, timezone
from typing import Dict, List, Tuple
from ..utils.aws import safe_api_call, paginate_all
from .evidence import activity_evidence, qualify_findings


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
                            "monthly_cost": None,
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

                        orphans.append({
                            "resource_id": alarm["AlarmName"],
                            "resource_type": "CloudWatch Alarm (stale)",
                            "category": "monitoring",
                            "region": region,
                            "reason": f"INSUFFICIENT_DATA for {age_days} days",
                            "age_days": age_days,
                            "monthly_cost": None,
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
                    if idle["status"] != "confirmed_observation":
                        errors.append(f"cloudwatch.GetMetricStatistics ({region}): {idle['missing_data_reason']}")
                    if idle["idle"] is not False:
                        age_days = None
                        if last_modified:
                            try:
                                dt = datetime.fromisoformat(last_modified.replace("Z", "+00:00"))
                                age_days = (datetime.now(timezone.utc) - dt).days
                            except Exception:
                                pass
                        orphans.append({
                            "resource_id": fn_name,
                            "resource_type": "Lambda Function",
                            "category": "monitoring",
                            "region": region,
                            "reason": "Lambda invocation observation: " + idle["status"],
                            "status": idle["status"], "evidence": idle,
                            "age_days": age_days,
                            "monthly_cost": None,
                            "created": last_modified or None,
                            "tags": {},
                            "cleanup_action": f"aws lambda delete-function --function-name {fn_name} --region {region}",
                            "confidence": "low",
                        })
        except Exception as e:
            errors.append(f"Lambda ({region}): {e}")

        if progress and task_id:
            progress.advance(task_id)

    return qualify_findings(orphans), errors


def _check_lambda_idle(cw, resource_id, *, now=None):
    """Return validated rolling-window activity evidence."""
    return activity_evidence(cw, "AWS/Lambda", "Invocations",
                             "FunctionName", resource_id, 90, now)
