"""Distinct tool schemas must cross the final MCP privacy boundary safely."""

import json

import pytest

pytest.importorskip("mcp")
from mcp.server.fastmcp.exceptions import ToolError

from kulshan.mcp_server import tools
from kulshan.pseudonym.engine import PseudonymizationEngine
from kulshan.pseudonym.policy import PseudonymPolicy


@pytest.mark.parametrize(
    "operation,payload,sensitive",
    [
        (
            "preflight",
            {"account_id": 123456789012, "arn": "arn:aws:iam::123456789012:role/Audit"},
            ["123456789012"],
        ),
        (
            "report",
            {
                "findings": [
                    {
                        "resource_id": "payroll-production-db",
                        "title": "Review payroll-production-db",
                    }
                ],
                "cost": 123456789012,
            },
            ["payroll-production-db"],
        ),
        (
            "quick_security",
            {
                "grouped_resources": ["finance-db", {"resource_id": "salary-db"}],
                "total_findings": 2,
            },
            ["finance-db", "salary-db"],
        ),
        (
            "analyze_ec2",
            {
                "nested": [{"account_ids": [123456789012], "quantity": 12}],
                "top_resources": [{"name": "payroll-ec2", "current_cost": 11}],
                "amount": -42.5,
            },
            ["123456789012", "payroll-ec2"],
        ),
        (
            "analyze_cost",
            {
                "resource_ids": ["ledger-db"],
                "unexpected": "ledger-db has cost movement",
                "total": 81,
            },
            ["ledger-db"],
        ),
        (
            "cur_validate",
            {"unexpected": {"account_id": 123456789012}, "row_count": 123456789012},
            ["123456789012"],
        ),
    ],
)
def test_final_mcp_json(monkeypatch, operation, payload, sensitive):
    engine = PseudonymizationEngine(b"t" * 32, PseudonymPolicy.for_persistence())
    monkeypatch.setattr("kulshan.pseudonym.context.create_engine_for_output", lambda *_: engine)

    class Process:
        returncode = 0

        def communicate(self, *args, **kwargs):
            return json.dumps({"status": "ok", "payload": json.dumps(payload)}), ""

    monkeypatch.setattr(tools.subprocess, "Popen", lambda *a, **kw: Process())
    result = json.loads(tools._run_isolated(operation, {}, 1, "retry"))
    assert result.keys() == payload.keys()

    def check(before, after, field=""):
        if isinstance(before, dict):
            assert before.keys() == after.keys()
            for key in before:
                check(before[key], after[key], key)
        elif isinstance(before, list):
            assert len(before) == len(after)
            for a, b in zip(before, after):
                check(a, b, field)
        elif field in {
            "account_id",
            "account_ids",
            "resource_id",
            "resource_ids",
            "grouped_resources",
        }:
            assert isinstance(after, str)
            assert str(before) != after
            assert all(value not in after for value in sensitive)
        elif field in {"cost", "quantity", "amount", "total", "row_count", "total_findings"}:
            assert after == before
        elif isinstance(after, str):
            assert all(value not in after for value in sensitive)

    check(payload, result)


def test_compact_findings_keep_semantics_until_privacy_boundary(monkeypatch):
    engine = PseudonymizationEngine(b"t" * 32, PseudonymPolicy.for_persistence())
    monkeypatch.setattr("kulshan.pseudonym.context.create_engine_for_output", lambda *_: engine)
    compact = tools._compact_finding(
        {
            "resource_id": "payroll-production-db",
            "title": "Review payroll-production-db",
            "account_id": 123456789012,
        }
    )
    result = tools._private_response(json.dumps(compact))
    assert "payroll-production-db" not in result
    assert "123456789012" not in result


def test_ranked_account_pairs_preserve_cost_and_embedded_labeled_names():
    engine = PseudonymizationEngine(b"t" * 32, PseudonymPolicy.for_persistence())
    result = engine.pseudonymize_payload(
        {
            "top_accounts": [[123456789012, 42.5]],
            "unexpected": "resource_id=staging-payroll-db needs review",
        }
    )
    assert result["top_accounts"][0][1] == 42.5
    assert isinstance(result["top_accounts"][0][0], str)
    assert "staging-payroll-db" not in result["unexpected"]


def test_identifier_names_cannot_rename_schema_or_corrupt_substrings():
    engine = PseudonymizationEngine(b"t" * 32, PseudonymPolicy.for_persistence())
    payload = {"resource_id": "cost", "cost": 123, "title": "cost changed", "unexpected": "costing"}
    result = engine.pseudonymize_payload(payload)
    assert result.keys() == payload.keys()
    assert result["cost"] == 123
    assert result["unexpected"] == "costing"
    assert result["resource_id"] != "cost"


def test_semantic_failure_is_closed(monkeypatch):
    engine = PseudonymizationEngine(b"t" * 32, PseudonymPolicy.for_persistence())
    monkeypatch.setattr("kulshan.pseudonym.context.create_engine_for_output", lambda *_: engine)
    monkeypatch.setattr(
        engine, "pseudonymize_value", lambda *a: (_ for _ in ()).throw(ValueError("secret"))
    )
    with pytest.raises(ToolError, match="output withheld"):
        tools._private_response('{"account_id":123456789012}')
