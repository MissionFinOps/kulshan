"""Every dynamic MCP tool crosses the same fail-closed boundary."""
import asyncio
import json

import pytest

pytest.importorskip("mcp")
from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.exceptions import ToolError

from kulshan.mcp_server import tools
from kulshan.pseudonym.engine import PseudonymizationEngine
from kulshan.pseudonym.policy import PseudonymPolicy


@pytest.mark.parametrize("operation", ["preflight", "report", "analyze_ec2", "analyze_cost", "cur_validate", "quick_security"])
def test_dynamic_response_privacy(monkeypatch, operation):
    engine = PseudonymizationEngine(b"t" * 32, PseudonymPolicy.for_persistence())
    monkeypatch.setattr("kulshan.pseudonym.context.create_engine_for_output", lambda *_: engine)
    raw = "123456789012 arn:aws:s3:::secret-project i-12345678 10.20.30.40 2001:db8::1"
    class Process:
        returncode = 0
        def communicate(self, *args, **kwargs):
            return json.dumps({"status": "ok", "payload": json.dumps({"text": raw, "cost": 123456789012})}), ""
    monkeypatch.setattr(tools.subprocess, "Popen", lambda *a, **k: Process())
    result = json.loads(tools._run_isolated(operation, {}, 1, "retry"))
    assert result["cost"] == 123456789012
    for identifier in raw.split():
        assert identifier not in result["text"]


def test_privacy_failure_withholds_raw_output(monkeypatch):
    monkeypatch.setattr("kulshan.pseudonym.context.create_engine_for_output", lambda *_: None)
    with pytest.raises(ToolError, match="output withheld"):
        tools._private_response('{"secret":"123456789012"}')


@pytest.mark.parametrize("result,status", [
    ({"findings": []}, "complete"),
    ({"findings": [{"severity": "high", "title": "finding"}]}, "complete"),
    ({"skipped": True, "errors": ["AccessDenied"]}, "unavailable"),
    ({"findings": [{"severity": "high"}], "errors": ["AccessDenied"]}, "partial"),
])
def test_security_preserves_coverage(monkeypatch, result, status):
    monkeypatch.setattr("kulshan.session.create_session", lambda: object())
    monkeypatch.setattr("kulshan.orchestrator.run_all_scans", lambda **kw: {"security": result})
    response = json.loads(tools._execute_quick_security("us-east-1"))
    assert response["status"] == status
    assert response["total_findings"] == len(result.get("findings", []))


def test_runtime_tool_discovery():
    server = FastMCP("test")
    tools.register_tools(server)
    registered = asyncio.run(server.list_tools())
    assert len(registered) == 7
    assert {tool.name for tool in registered} >= {"kulshan_quick_security", "kulshan_analyze_cost"}
