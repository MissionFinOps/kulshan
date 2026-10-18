"""Offline regressions for sweep evidence integrity."""

from datetime import UTC, datetime, timedelta
from unittest.mock import Mock

import pytest

from kulshan.checks.sweep.scanner.monitoring import _check_lambda_idle
from kulshan.checks.sweep.scanner.network import _check_nat_idle


@pytest.mark.parametrize("check,days", [(_check_nat_idle, 14), (_check_lambda_idle, 90)])
def test_missing_metrics_are_unknown(check, days):
    cw = Mock()
    cw.get_metric_statistics.return_value = {"Datapoints": []}
    result = check(cw, "resource")
    assert result["status"] == "insufficient_evidence"
    assert result["observed_activity"] is None
    call = cw.get_metric_statistics.call_args.kwargs
    assert call["EndTime"] - call["StartTime"] == timedelta(days=days)


@pytest.mark.parametrize(
    "end",
    [
        datetime(2024, 3, 1, tzinfo=UTC),
        datetime(2025, 1, 1, tzinfo=UTC),
        datetime(2024, 12, 31, tzinfo=UTC),
    ],
)
@pytest.mark.parametrize("check,days", [(_check_nat_idle, 14), (_check_lambda_idle, 90)])
def test_rolling_window_and_complete_zero(check, days, end):
    cw = Mock()
    start = end - timedelta(days=days)
    cw.get_metric_statistics.return_value = {
        "Datapoints": [{"Timestamp": start + timedelta(days=i), "Sum": 0} for i in range(days)]
    }
    result = check(cw, "resource", now=end)
    assert result["status"] == "confirmed_observation"
    assert result["idle"] is True
    assert result["coverage"] == 1


def test_partial_metrics_and_nonzero():
    end = datetime(2025, 1, 1, tzinfo=UTC)
    cw = Mock()
    points = [{"Timestamp": end - timedelta(days=i + 1), "Sum": 0} for i in range(7)]
    cw.get_metric_statistics.return_value = {"Datapoints": points}
    result = _check_nat_idle(cw, "nat", now=end)
    assert result["status"] == "insufficient_evidence"
    assert result["coverage"] == 0.5
    points[0]["Sum"] = 1
    assert _check_nat_idle(cw, "nat", now=end)["idle"] is False


@pytest.mark.parametrize(
    "point",
    [
        {},
        {"Sum": float("nan")},
        {"Sum": -1},
        {"Sum": 0, "Timestamp": datetime(2000, 1, 1, tzinfo=UTC)},
    ],
)
def test_invalid_metrics(point):
    cw = Mock()
    cw.get_metric_statistics.return_value = {"Datapoints": [point]}
    assert _check_nat_idle(cw, "nat")["status"] == "insufficient_evidence"


def test_metric_failure():
    cw = Mock()
    cw.get_metric_statistics.side_effect = TimeoutError("timeout")
    assert _check_lambda_idle(cw, "fn")["status"] == "could_not_check"


KEYS = {
    "describe_security_groups": "SecurityGroups",
    "describe_network_interfaces": "NetworkInterfaces",
    "describe_nat_gateways": "NatGateways",
    "describe_load_balancers": "LoadBalancers",
    "describe_target_groups": "TargetGroups",
    "describe_target_health": "TargetHealthDescriptions",
    "describe_volumes": "Volumes",
    "describe_addresses": "Addresses",
    "describe_images": "Images",
    "describe_instances": "Reservations",
    "describe_snapshots": "Snapshots",
    "describe_db_snapshots": "DBSnapshots",
    "describe_db_instances": "DBInstances",
    "describe_log_groups": "logGroups",
    "describe_alarms": "MetricAlarms",
    "list_functions": "Functions",
    "describe_repositories": "repositories",
    "list_images": "imageIds",
    "list_buckets": "Buckets",
}


class Client:
    def __init__(self):
        self.responses = {}
        self.partial = set()

    def can_paginate(self, method):
        return method in self.partial

    def __getattr__(self, method):
        def call(**kwargs):
            response = self.responses.get(method, {KEYS.get(method, "unknown"): []})
            if isinstance(response, Exception):
                raise response
            return response(**kwargs) if callable(response) else response

        return call

    def get_paginator(self, method):
        client = self

        class Paginator:
            def paginate(self, **kwargs):
                yield getattr(client, method)(**kwargs)
                if method in client.partial:
                    raise TimeoutError("partial pagination timeout")

        return Paginator()


class Session:
    def __init__(self):
        self.clients = {}

    def client(self, service, region_name=None):
        return self.clients.setdefault((service, region_name), Client())


@pytest.mark.parametrize("failure", ["denied", "timeout", "throttled", "malformed", "partial"])
@pytest.mark.parametrize("dependency", ["eni", "target_groups", "health", "volumes", "instances"])
def test_failed_dependencies_never_become_empty(dependency, failure, monkeypatch):
    from botocore.exceptions import ClientError

    from kulshan.checks.sweep.scanner.compute import scan_compute
    from kulshan.checks.sweep.scanner.network import scan_network

    monkeypatch.setattr("kulshan.aws_runtime.time.sleep", lambda _: None)
    session = Session()
    region = "eu-west-1"
    ec2, elb = (session.client(s, region_name=region) for s in ["ec2", "elbv2"])
    now = datetime.now(UTC)
    ec2.responses.update(
        {
            "describe_security_groups": {
                "SecurityGroups": [{"GroupId": "sg-unused", "GroupName": "custom"}]
            },
            "describe_snapshots": {
                "Snapshots": [
                    {"SnapshotId": "snap-backup", "VolumeId": "vol-old", "StartTime": now}
                ]
            },
            "describe_volumes": lambda **kw: (
                {"Volumes": [{"VolumeId": "vol-review", "CreateTime": now}]}
                if kw
                else {"Volumes": []}
            ),
            "describe_images": {"Images": [{"ImageId": "ami-recovery"}]},
        }
    )
    elb.responses.update(
        {
            "describe_load_balancers": {
                "LoadBalancers": [{"LoadBalancerArn": "arn:lb", "LoadBalancerName": "lb"}]
            },
            "describe_target_groups": {"TargetGroups": [{"TargetGroupArn": "arn:tg"}]},
        }
    )
    client, operation, forbidden = {
        "eni": (ec2, "describe_network_interfaces", "Security Group"),
        "target_groups": (elb, "describe_target_groups", "Load Balancer (application)"),
        "health": (elb, "describe_target_health", "Load Balancer (application)"),
        "volumes": (ec2, "describe_volumes", "EBS Snapshot"),
        "instances": (ec2, "describe_instances", "AMI"),
    }[dependency]
    if failure == "partial":
        client.partial.add(operation)
    elif failure == "malformed":
        client.responses[operation] = {}
    elif failure == "timeout":
        client.responses[operation] = TimeoutError("network timeout")
    else:
        code = "AccessDenied" if failure == "denied" else "Throttling"
        client.responses[operation] = ClientError(
            {"Error": {"Code": code, "Message": code}}, operation
        )
    scanner = scan_network if dependency in {"eni", "target_groups", "health"} else scan_compute
    findings, errors = scanner(session, [region])
    assert not any(f["resource_type"] == forbidden for f in findings)
    assert any(operation in e and region in e for e in errors)
    if dependency == "instances":
        assert any(f["resource_id"] == "vol-review" for f in findings)


def test_successful_empty_dependencies_are_review_candidates():
    from kulshan.checks.sweep.scanner.network import scan_network

    session = Session()
    session.client("ec2", region_name="us-east-1").responses["describe_security_groups"] = {
        "SecurityGroups": [{"GroupId": "sg-review", "GroupName": "custom"}]
    }
    findings, errors = scan_network(session, ["us-east-1"])
    assert not errors
    assert len(findings) == 1
    assert findings[0]["status"] == "review_candidate"
    assert findings[0]["monthly_cost"] is None
    assert "Manual review" in findings[0]["cleanup_action"]


@pytest.mark.parametrize(
    "operation,response",
    [
        ("describe_network_interfaces", {"NetworkInterfaces": [{"NetworkInterfaceId": "eni-x"}]}),
        ("describe_instances", {"Reservations": [{}]}),
        ("describe_target_health", {"TargetHealthDescriptions": [{}]}),
    ],
)
def test_nested_malformed_inventory_rejected(operation, response):
    from kulshan.checks.sweep.utils.aws import safe_api_call

    client = Client()
    client.responses[operation] = response
    result, error = safe_api_call(client, operation)
    assert result is None
    assert "malformed" in error


@pytest.mark.parametrize(
    "points",
    [None, [{}], [{"Timestamp": "bad", "Sum": 0}], [{"Timestamp": datetime(2025, 1, 1), "Sum": 0}]],
)
def test_malformed_metric_shapes(points):
    cw = Mock()
    cw.get_metric_statistics.return_value = {"Datapoints": points}
    assert _check_lambda_idle(cw, "fn")["idle"] is None


def test_duplicate_and_out_of_window_metrics():
    end = datetime(2025, 1, 1, tzinfo=UTC)
    cw = Mock()
    point = {"Timestamp": end - timedelta(days=1), "Sum": 0}
    for points in [
        [point, point],
        [point, {"Timestamp": end, "Sum": 0}],
        [{**point, "Sum": float("inf")}],
        [{**point, "Sum": True}],
    ]:
        cw.get_metric_statistics.return_value = {"Datapoints": points}
        assert _check_nat_idle(cw, "nat", now=end)["status"] == "insufficient_evidence"


def test_run_scan_partial_and_unknown_contract():
    from kulshan.checks.sweep import run_scan
    from kulshan.coverage import build_coverage_from_results

    session = Session()
    ec2 = session.client("ec2", region_name="us-east-1")
    ec2.responses["describe_volumes"] = {"Volumes": [{"VolumeId": "vol-review", "Size": 100}]}
    ec2.responses["describe_instances"] = TimeoutError("timeout")
    result = run_scan(session, ["us-east-1"])
    assert result["partial"] is True
    assert result["scores"]["overall_score"] is None
    assert result["scores"]["monthly_waste"] is None
    assert result["findings"]
    assert all(f["estimated_monthly_impact"] is None for f in result["findings"])
    coverage = build_coverage_from_results({"sweep": result}, ["us-east-1"], 1).to_dict()
    assert coverage["summary"]["report_status"] == "partial"
    assert any(record.get("errors") for record in result["coverage"])


def test_all_scanners_unavailable():
    from kulshan.checks.sweep import run_scan

    class Unavailable:
        def client(self, *args, **kwargs):
            raise TimeoutError("offline")

    result = run_scan(Unavailable(), ["us-east-1"])
    assert not result["findings"]
    assert result["scores"]["overall_score"] is None
    assert result["scores"]["grade"] == "N/A"
    assert result["partial"]


def test_canonical_unknown_roundtrip_and_renderers():
    import json
    from io import StringIO

    from rich.console import Console

    from kulshan.adapter import adapt
    from kulshan.checks.sweep import _orphan_to_finding
    from kulshan.checks.sweep.scanner.evidence import qualify_findings
    from kulshan.models import Finding
    from kulshan.report.csv_export import findings_to_csv
    from kulshan.report.html import _build_what_to_do_next
    from kulshan.report.terminal import _render_top_actions

    raw = qualify_findings(
        [
            {
                "resource_id": "vol-review",
                "resource_type": "EBS Volume",
                "region": "eu-west-1",
                "reason": "Unattached",
                "monthly_cost": 99,
            }
        ]
    )[0]
    finding = adapt("sweep", _orphan_to_finding(raw))
    serialized = Finding.from_dict(finding).to_dict()
    assert serialized["estimated_monthly_impact"] is None
    assert serialized["evidence"]["financial"]["semantics"] == "unknown"
    assert "orphaned" not in serialized["title"]
    assert "99" not in json.dumps(serialized)
    assert "review_candidate" in findings_to_csv([serialized])
    assert "Unknown" in _build_what_to_do_next([serialized], ["sweep"])
    output = StringIO()
    _render_top_actions(Console(file=output), [serialized])
    assert "Unknown" in output.getvalue()


def billing_evidence(**changes):
    from kulshan.analyze.models import CostBasis

    return {
        "resource_id": "vol-review",
        "region": "eu-west-1",
        "semantics": "observed_billed_cost",
        "source": "cur_parquet",
        "value": "123.456789",
        "period_start": "2025-01-01T00:00:00+00:00",
        "period_end": "2025-02-01T00:00:00+00:00",
        "cost_basis": CostBasis(column="net_unblended_cost", currency="CAD"),
        **changes,
    }


def test_attributed_billing_preserves_currency_and_provenance():
    from kulshan.checks.sweep import run_scan

    session = Session()
    session.client("ec2", region_name="eu-west-1").responses["describe_volumes"] = {
        "Volumes": [{"VolumeId": "vol-review"}]
    }
    result = run_scan(
        session, ["eu-west-1"], financial_evidence={("eu-west-1", "vol-review"): billing_evidence()}
    )
    finding = next(f for f in result["findings"] if f["resource_id"] == "vol-review")
    financial = finding["evidence"]["financial"]
    assert financial["value"] == "123.456789"
    assert financial["currency"] == "CAD"
    assert financial["source"] == "cur_parquet"
    assert financial["potential_avoidable_cost"] is None
    assert finding["estimated_monthly_impact"] is None
    assert result["scores"]["monthly_waste"] is None


@pytest.mark.parametrize(
    "change",
    [
        {"region": "us-west-2"},
        {"resource_id": "vol-other"},
        {"source": "generic_price"},
        {"value": "NaN"},
        {"period_start": "invalid"},
    ],
)
def test_invalid_billing_evidence_is_unknown(change):
    from kulshan.checks.sweep.scanner.evidence import attributable_billing, qualify_findings

    finding = qualify_findings(
        [
            {
                "resource_id": "vol-review",
                "resource_type": "EBS Volume",
                "region": "eu-west-1",
                "reason": "Unattached",
            }
        ]
    )[0]
    assert attributable_billing(finding, billing_evidence(**change))["semantics"] == "unknown"


def test_mcp_sweep_evidence_privacy(monkeypatch):
    import json

    pytest.importorskip("mcp")
    from kulshan.mcp_server.tools import _private_response
    from kulshan.pseudonym.engine import PseudonymizationEngine
    from kulshan.pseudonym.policy import PseudonymPolicy

    engine = PseudonymizationEngine(b"t" * 32, PseudonymPolicy.for_persistence())
    monkeypatch.setattr("kulshan.pseudonym.context.create_engine_for_output", lambda *_: engine)
    response = json.loads(
        _private_response(
            json.dumps(
                {
                    "evidence": {
                        "resource_id": "vol-0123456789abcdef0",
                        "finding_status": "insufficient_evidence",
                        "observed_activity": None,
                        "financial": {"semantics": "unknown", "value": None, "currency": "CAD"},
                        "coverage": 0.5,
                    }
                }
            )
        )
    )
    assert "vol-0123456789abcdef0" not in json.dumps(response)
    assert response["evidence"]["observed_activity"] is None
    assert response["evidence"]["financial"]["value"] is None
    assert response["evidence"]["financial"]["currency"] == "CAD"
    assert response["evidence"]["coverage"] == 0.5


@pytest.mark.parametrize("response", [{}, {"Datapoints": []}, {"Datapoints": None}])
def test_missing_metric_shapes_have_no_idle_claim(response):
    cw = Mock()
    cw.get_metric_statistics.return_value = response
    result = _check_nat_idle(cw, "nat")
    assert result["idle"] is None
    assert result["observed_activity"] is None


def test_cloudwatch_access_denied():
    from botocore.exceptions import ClientError

    cw = Mock()
    cw.get_metric_statistics.side_effect = ClientError(
        {"Error": {"Code": "AccessDenied", "Message": "denied"}}, "GetMetricStatistics"
    )
    result = _check_lambda_idle(cw, "fn")
    assert result["status"] == "could_not_check"
    assert "AccessDenied" in result["missing_data_reason"]


def test_complete_nonzero_and_overflow():
    end = datetime(2025, 1, 1, tzinfo=UTC)
    cw = Mock()
    points = [{"Timestamp": end - timedelta(days=i + 1), "Sum": 0} for i in range(14)]
    points[3]["Sum"] = 1
    cw.get_metric_statistics.return_value = {"Datapoints": points}
    assert _check_nat_idle(cw, "nat", now=end)["idle"] is False
    for point in points:
        point["Sum"] = 1e308
    result = _check_nat_idle(cw, "nat", now=end)
    assert result["status"] == "insufficient_evidence"
    assert result["observed_activity"] is None


def test_wrong_metric_unit():
    cw = Mock()
    cw.get_metric_statistics.return_value = {
        "Datapoints": [{"Timestamp": datetime.now(UTC), "Sum": 0, "Unit": "Seconds"}]
    }
    assert _check_lambda_idle(cw, "fn")["status"] == "insufficient_evidence"


@pytest.mark.parametrize(
    "service,operation,key,item",
    [
        ("ecr", "list_images", "repositories", {"repositoryName": "repo"}),
        ("s3", "list_objects_v2", "Buckets", {"Name": "bucket"}),
    ],
)
def test_storage_dependency_failures(service, operation, key, item):
    from kulshan.checks.sweep.scanner.storage import scan_storage

    session = Session()
    client = session.client(service, region_name="us-east-1")
    discovery = "describe_repositories" if service == "ecr" else "list_buckets"
    client.responses[discovery] = {key: [item]}
    client.responses[operation] = TimeoutError("timeout")
    findings, errors = scan_storage(session, ["us-east-1"])
    assert not findings
    assert any(operation in error for error in errors)


def test_region_isolation_and_consolidated_failure_details():
    from kulshan.checks.sweep import run_scan
    from kulshan.coverage import build_coverage_from_results

    session = Session()
    session.client("ec2", region_name="eu-west-1").responses["describe_volumes"] = {
        "Volumes": [{"VolumeId": "vol-review"}]
    }
    session.client("ec2", region_name="us-east-1").responses["describe_instances"] = TimeoutError(
        "timeout"
    )
    regions = ["eu-west-1", "us-east-1"]
    result = run_scan(session, regions)
    assert any(f["resource_id"] == "vol-review" for f in result["findings"])
    records = build_coverage_from_results({"sweep": result}, regions, 1).to_dict()["executions"]
    compute = [r for r in records if r["check"] == "compute"]
    assert next(r for r in compute if r["region"] == "eu-west-1")["status"] == "complete"
    failed = next(r for r in compute if r["region"] == "us-east-1")
    assert failed["status"] == "partial"
    assert failed["errors"][0]["service"] == "ec2"
    assert failed["errors"][0]["action"] == "describe_instances"


def test_empty_regions_and_no_completion_evidence():
    from kulshan.checks.sweep import run_scan
    from kulshan.checks.sweep.scoring.engine import calculate_score

    assert run_scan(Session(), [])["scores"]["overall_score"] is None
    assert calculate_score([])["overall_score"] is None


def test_compact_mcp_preserves_sweep_contract_and_privacy(monkeypatch):
    import json

    pytest.importorskip("mcp")
    from kulshan.mcp_server.tools import _compact_finding, _private_response
    from kulshan.pseudonym.engine import PseudonymizationEngine
    from kulshan.pseudonym.policy import PseudonymPolicy

    engine = PseudonymizationEngine(b"t" * 32, PseudonymPolicy.for_persistence())
    monkeypatch.setattr("kulshan.pseudonym.context.create_engine_for_output", lambda *_: engine)
    raw = {
        "pack": "sweep",
        "region": "eu-west-1",
        "confidence": 0.4,
        "estimated_monthly_impact": None,
        "evidence": {
            "resource_id": "rare-recovery-function",
            "finding_status": "review_candidate",
            "coverage": 0.5,
            "observed_activity": None,
            "financial": {
                "semantics": "observed_billed_cost",
                "value": "123.456789",
                "currency": "CAD",
            },
        },
    }
    compact = json.loads(_private_response(json.dumps(_compact_finding(raw))))
    assert compact["dollar_impact"] is None
    assert compact["evidence"]["finding_status"] == "review_candidate"
    assert compact["evidence"]["financial"]["value"] == "123.456789"
    assert compact["evidence"]["financial"]["currency"] == "CAD"
    assert compact["evidence"]["coverage"] == 0.5
    assert "rare-recovery-function" not in json.dumps(compact)


def test_sarif_retains_evidence_without_savings():
    from kulshan.report.sarif import findings_to_sarif

    finding = {
        "pack": "sweep",
        "severity": "info",
        "kind": "idle-lambda",
        "title": "Lambda: insufficient_evidence",
        "estimated_monthly_impact": None,
        "evidence": {
            "finding_status": "insufficient_evidence",
            "financial": {"semantics": "unknown", "value": None},
        },
    }
    result = findings_to_sarif([finding])["runs"][0]["results"][0]
    assert result["properties"]["evidence"] == finding["evidence"]
    assert "estimatedMonthlySavingsUSD" not in result["properties"]
