"""Security Git Blame, CloudTrail attribution for who created each risk."""

import boto3
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional
from .scanner.base import Finding
from .utils.aws import safe_api_call

# Map check_ids to CloudTrail event names that would create the finding
CHECK_TO_EVENTS = {
    "NET-001": ["AuthorizeSecurityGroupIngress", "CreateSecurityGroup"],
    "NET-002": ["AuthorizeSecurityGroupIngress", "CreateSecurityGroup"],
    "NET-003": ["AuthorizeSecurityGroupIngress", "CreateSecurityGroup"],
    "IAM-005": ["AttachUserPolicy", "PutUserPolicy", "AttachGroupPolicy", "PutGroupPolicy"],
    "IAM-007": ["CreateRole", "UpdateAssumeRolePolicy"],
    "DATA-002": ["PutBucketPolicy", "PutBucketAcl", "DeletePublicAccessBlock"],
    "DATA-005": ["CreateDBInstance", "ModifyDBInstance"],
    "COMP-001": ["RunInstances", "ModifyInstanceMetadataOptions"],
    "COMP-003": ["CreateFunction20150331", "UpdateFunctionConfiguration20150331v2"],
    "LOG-003": ["StopLogging"],
}


def blame_findings(session: boto3.Session, findings: List[Finding],
                   max_findings: int = 20) -> List[Dict]:
    """Attribute findings to CloudTrail events (who created the risk and when)."""
    results = []
    ct = session.client("cloudtrail", region_name="us-east-1")

    # Only blame critical and high findings, up to max
    target_findings = [f for f in findings if f.check_id in CHECK_TO_EVENTS][:max_findings]

    for f in target_findings:
        event_names = CHECK_TO_EVENTS.get(f.check_id, [])
        if not event_names:
            continue

        attribution = {
            "check_id": f.check_id,
            "title": f.title,
            "resource_id": f.resource_id,
            "region": f.region,
            "severity": f.severity.value,
            "created_by": None,
            "created_on": None,
            "event_name": None,
            "age_days": None,
        }

        # Search CloudTrail for the event (last 90 days free lookup)
        for event_name in event_names:
            try:
                lookup_attrs = [{"AttributeKey": "EventName", "AttributeValue": event_name}]
                events, err = safe_api_call(ct, "lookup_events",
                    LookupAttributes=lookup_attrs, MaxResults=50)
                if err or not events:
                    continue

                for event in events.get("Events", []):
                    # Match by resource
                    resources = event.get("Resources", [])
                    resource_names = [r.get("ResourceName", "") for r in resources]
                    if f.resource_id in resource_names or any(f.resource_id in rn for rn in resource_names):
                        event_time = event.get("EventTime")
                        if event_time:
                            if isinstance(event_time, str):
                                event_time = datetime.fromisoformat(event_time)
                            if not event_time.tzinfo:
                                event_time = event_time.replace(tzinfo=timezone.utc)
                            age = (datetime.now(timezone.utc) - event_time).days
                            attribution["created_by"] = event.get("Username", "unknown")
                            attribution["created_on"] = event_time.strftime("%Y-%m-%d %H:%M")
                            attribution["event_name"] = event_name
                            attribution["age_days"] = age
                            break
                if attribution["created_by"]:
                    break
            except Exception:
                continue

        results.append(attribution)

    return results
