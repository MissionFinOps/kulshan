"""Final MCP JSON must preserve schema values while protecting identifiers."""

import json

import pytest

pytest.importorskip("mcp")
from mcp.server.fastmcp.exceptions import ToolError

from kulshan.mcp_server import tools
from kulshan.pseudonym.engine import PseudonymizationEngine
from kulshan.pseudonym.policy import PseudonymPolicy

COLLISIONS = [
    "high",
    "critical",
    "low",
    "USD",
    "CAD",
    "cost",
    "complete",
    "unknown",
    "EC2",
    "us-east-1",
]


def final_response(monkeypatch, engine, payload):
    monkeypatch.setattr("kulshan.pseudonym.context.create_engine_for_output", lambda *_: engine)

    class Process:
        returncode = 0

        def communicate(self, *args, **kwargs):
            return json.dumps({"status": "ok", "payload": json.dumps(payload)}), ""

    monkeypatch.setattr(tools.subprocess, "Popen", lambda *a, **kw: Process())
    return json.loads(tools._run_isolated("report", {}, 1, "retry"))


@pytest.mark.parametrize("name", COLLISIONS)
def test_identifier_collision_preserves_final_mcp_schema(monkeypatch, name):
    engine = PseudonymizationEngine(b"a" * 32, PseudonymPolicy.for_persistence())
    metadata = {
        "severity": "high",
        "currency": "USD",
        "confidence": "low",
        "status": "complete",
        "region": "us-east-1",
        "regions": ["us-east-1", "eu-west-1"],
        "service": "EC2",
        "state": "unknown",
        "amount": 123456789012,
        "cost": -42.5,
        "quantity": 8,
        "enabled": True,
        "estimated": False,
        "variants": [{"severity": "critical", "currency": "CAD"}, {"severity": "low"}],
    }
    payload = {
        "resource_id": name,
        "resource_name": name,
        "account_id": 123456789012,
        "metadata": metadata,
        "grouped_resources": [name, {"resource_id": name, "metadata": metadata}],
        "top_resources": [{"name": name, "current_cost": 42.5}],
        "title": f"Resource {name} needs review",
        "unexpected": f"Investigate {name} before proceeding",
        "schema_keys": {name: 42.5},
    }
    result = final_response(monkeypatch, engine, payload)
    # Confidentiality and integrity must hold simultaneously in the same response.
    assert result.keys() == payload.keys()
    assert result["schema_keys"] == payload["schema_keys"]
    assert result["metadata"] == metadata
    assert result["grouped_resources"][1]["metadata"] == metadata
    alias = result["resource_id"]
    assert alias.startswith("res_") and alias != name
    assert result["resource_name"] == alias
    assert result["grouped_resources"][0] == alias
    assert result["grouped_resources"][1]["resource_id"] == alias
    assert result["top_resources"][0] == {"name": alias, "current_cost": 42.5}
    assert result["account_id"].startswith("acct_")
    assert "123456789012" not in result["account_id"]
    assert name not in result["title"]
    assert name not in result["unexpected"]
    assert final_response(monkeypatch, engine, payload) == result
    other = PseudonymizationEngine(b"b" * 32, PseudonymPolicy.for_persistence())
    assert final_response(monkeypatch, other, payload)["resource_id"] != alias


@pytest.mark.parametrize("name", COLLISIONS)
def test_collision_alias_failure_withholds_final_mcp_output(monkeypatch, name):
    engine = PseudonymizationEngine(b"a" * 32, PseudonymPolicy.for_persistence())

    def fail(*args, **kwargs):
        raise RuntimeError("sensitive content must not appear in the error")

    monkeypatch.setattr(engine, "pseudonymize_value", fail)
    with pytest.raises(ToolError, match="output withheld") as error:
        final_response(monkeypatch, engine, {"resource_id": name, "severity": "high"})
    assert "sensitive content" not in str(error.value)


def test_distinctive_free_text_reference_and_original_examples(monkeypatch):
    engine = PseudonymizationEngine(b"a" * 32, PseudonymPolicy.for_persistence())
    payload = {
        "account_id": 123456789012,
        "resource_id": "payroll-production-db",
        "grouped_resources": ["finance-db", {"name": "salary-db", "quantity": 2}],
        "nested": [{"account_ids": [123456789012], "amount": 123456789012}],
        "title": "Investigate payroll-production-db and finance-db",
        "description": "Account 123456789012 has i-12345678 at 10.20.30.40",
        "status": "partial",
        "currency": "CAD",
    }
    result = final_response(monkeypatch, engine, payload)
    assert result["title"] == (
        "Investigate " + result["resource_id"] + " and " + result["grouped_resources"][0]
    )
    assert result["nested"][0]["amount"] == 123456789012
    assert result["status"] == "partial" and result["currency"] == "CAD"
    assert result["grouped_resources"][1]["quantity"] == 2
    assert "salary-db" not in json.dumps(result["grouped_resources"])
    for identifier in ("123456789012", "i-12345678", "10.20.30.40"):
        assert identifier not in result["description"]
