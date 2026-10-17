"""Offline regressions for the 4252c6c stabilization."""

from datetime import date
from unittest.mock import Mock

import pytest

from kulshan.checks.cost.cost_fetcher import CostFetcher
from kulshan.orchestrator import summarize_completeness


@pytest.mark.parametrize("identity", ["direct", "profile", "assumed-other-account"])
def test_cost_fetcher_uses_verified_identity(monkeypatch, identity):
    session = Mock(name=identity)
    constructor = Mock(side_effect=AssertionError("must not construct a fallback session"))
    monkeypatch.setattr("boto3.Session", constructor)
    CostFetcher(profile="wrong-account", session=session)
    assert [call.args[0] for call in session.client.call_args_list] == ["ce", "organizations"]


def test_cost_fetcher_standalone_profile(monkeypatch):
    constructor = Mock()
    monkeypatch.setattr("boto3.Session", constructor)
    CostFetcher(profile="selected")
    constructor.assert_called_once_with(profile_name="selected")


def test_cost_fetcher_missing_credentials_never_falls_back(monkeypatch):
    session = Mock()
    session.client.side_effect = RuntimeError("missing credentials")
    constructor = Mock(side_effect=AssertionError("fallback"))
    monkeypatch.setattr("boto3.Session", constructor)
    with pytest.raises(RuntimeError, match="missing credentials"):
        CostFetcher(session=session)
    constructor.assert_not_called()


@pytest.mark.parametrize(
    "results,status",
    [
        ({"cost": {}}, "complete"),
        ({"cost": {"findings": [{"severity": "high"}]}}, "complete"),
        ({"cost": {"errors": ["AccessDenied"]}}, "partial"),
        ({"cost": {"skipped": True}}, "unavailable"),
        ({}, "unavailable"),
        ({"cost": {}, "security": {"skipped": True}}, "partial"),
    ],
)
def test_completeness(results, status):
    assert summarize_completeness(results)["status"] == status


@pytest.mark.parametrize("result,code", [
    ({}, 0), ({"scores": {"severity_counts": {"critical": 1}}}, 1),
    ({"errors": ["AccessDenied"]}, 2), ({"skipped": True}, 2),
])
def test_scan_process_status(result, code):
    from kulshan.orchestrator import scan_exit_code
    assert scan_exit_code({"security": result}) == code


def test_cost_pack_passes_injected_session(monkeypatch):
    import pandas as pd

    from kulshan.checks.cost import run_scan
    session = Mock()
    fetcher = Mock()
    fetcher.get_cost_by_dimension.return_value = pd.DataFrame()
    factory = Mock(return_value=fetcher)
    monkeypatch.setattr("kulshan.checks.cost.cost_fetcher.CostFetcher", factory)
    run_scan(session=session, profile="wrong")
    factory.assert_called_once_with(profile="wrong", session=session)


def test_prior_month_does_not_prove_reconciliation():
    from kulshan.billing_integrity import assess_billing_integrity

    result = assess_billing_integrity("2025-12", today=date(2026, 1, 2))
    assert result.period_finality == "unknown"
    assert result.status == "unknown"


@pytest.mark.parametrize(
    "column", ["cost_category_secret_project", "line_item_line_item_description"]
)
def test_customer_text_is_not_safe(column):
    from kulshan.export.columns import ColumnClass, classify_column

    assert classify_column(column) is ColumnClass.PSEUDONYMIZE


@pytest.mark.parametrize("value", ["=1+1", "  +cmd", "\t@SUM(1)", "\r-1+cmd"])
def test_csv_formula_protection(value):
    from kulshan.csv_safety import safe_csv_value

    assert safe_csv_value(value).startswith("'")


@pytest.mark.parametrize("value", [-42, "-42.50", "-1e3", 123456789012.0])
def test_csv_preserves_numbers(value):
    from kulshan.csv_safety import safe_csv_value

    assert safe_csv_value(value) == value


def test_privacy_unknown_fields_and_numeric_evidence():
    from kulshan.pseudonym.engine import PseudonymizationEngine
    from kulshan.pseudonym.policy import PseudonymPolicy

    engine = PseudonymizationEngine(b"x" * 32, PseudonymPolicy.for_persistence())
    identifiers = ["2001:db8::1234", "10.20.30.40", "arn:aws:s3:::secret-project", "vpc-12345678"]
    for value in identifiers:
        assert value not in str(engine.pseudonymize_payload({"unexpected": f"context {value}"}))
    assert engine.pseudonymize_payload({"cost": 123456789012})["cost"] == 123456789012


def test_export_residual_ipv6():
    from kulshan.export.gates import gate_residual

    assert not gate_residual(set(), "customer 2001:db8::1234").passed


def test_secret_detection_preserves_hashes_and_protects_credentials():
    from kulshan.redact import redact_payload, redact_text
    digest = "a" * 40
    secret = "aB1/" * 10
    assert redact_text(digest) == digest
    assert secret not in redact_text(f"aws_secret_access_key={secret}")
    assert secret not in str(redact_payload({"secret_key": secret}))


def test_required_privacy_cannot_degrade(monkeypatch):
    from kulshan.cli import _get_pseudonym_engine
    monkeypatch.setattr("kulshan.pseudonym.context.create_engine_for_output", lambda *_: None)
    with pytest.raises(RuntimeError, match="withheld"):
        _get_pseudonym_engine(fmt="json", output=None, show_pii=False)
