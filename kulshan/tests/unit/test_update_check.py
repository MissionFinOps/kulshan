"""Tests for the consent-first PyPI update check."""

from __future__ import annotations

from datetime import date
from io import StringIO
from unittest.mock import patch

from kulshan.update_check import prompt_for_update_check, release_age_text


class TTYInput(StringIO):
    def isatty(self) -> bool:
        return True


class NonTTYInput(StringIO):
    def isatty(self) -> bool:
        return False


def test_release_age_uses_local_date_only() -> None:
    assert release_age_text("2026-07-25", date(2026, 7, 25)) == "released today"
    assert release_age_text("2026-07-25", date(2026, 7, 26)) == "released 1 day ago"
    assert release_age_text("2026-07-25", date(2026, 8, 4)) == "released 10 days ago"


def test_noninteractive_run_never_prompts_or_contacts_pypi() -> None:
    with (
        patch("kulshan.update_check.click.confirm") as confirm,
        patch("kulshan.update_check.fetch_latest_version") as fetch,
    ):
        prompt_for_update_check(
            "0.4.5",
            "2026-07-25",
            stdin=NonTTYInput(),
            stderr=StringIO(),
        )

    confirm.assert_not_called()
    fetch.assert_not_called()


def test_declining_consent_does_not_contact_pypi(tmp_path) -> None:
    output = StringIO()
    with (
        patch("kulshan.update_check.click.confirm", return_value=False),
        patch("kulshan.update_check.fetch_latest_version") as fetch,
    ):
        prompt_for_update_check(
            "0.4.5",
            "2026-07-25",
            stdin=TTYInput(),
            stderr=output,
            state_path=tmp_path / "update-check.json",
        )

    fetch.assert_not_called()
    assert "July 25, 2026" in output.getvalue()
    assert "Check PyPI for a newer version?" in output.getvalue()
    assert "No AWS account, credentials, profile, workspace" in output.getvalue()


def test_consent_fetches_and_reports_newer_version(tmp_path) -> None:
    output = StringIO()
    with (
        patch("kulshan.update_check.click.confirm", return_value=True),
        patch(
            "kulshan.update_check.fetch_latest_version",
            return_value="0.4.6",
        ) as fetch,
    ):
        prompt_for_update_check(
            "0.4.5",
            "2026-07-25",
            stdin=TTYInput(),
            stderr=output,
            state_path=tmp_path / "update-check.json",
        )

    fetch.assert_called_once_with("0.4.5")
    assert "Kulshan 0.4.6 is available" in output.getvalue()
    assert "Manual installation required" in output.getvalue()
    assert "will never install updates automatically" in output.getvalue()
    assert "python -m pip install --upgrade kulshan" in output.getvalue()


def test_root_cli_invokes_update_prompt_before_landing_page() -> None:
    from click.testing import CliRunner
    from kulshan.cli import main

    with patch("kulshan.update_check.prompt_for_update_check") as prompt:
        result = CliRunner().invoke(main, [])

    assert result.exit_code == 0
    prompt.assert_called_once_with("0.4.12", "2026-07-27")


def test_update_prompt_precedes_preflight_aws_access() -> None:
    from click.testing import CliRunner
    from kulshan.cli import main

    marker = RuntimeError("stop after update prompt")
    with (
        patch(
            "kulshan.update_check.prompt_for_update_check",
            side_effect=marker,
        ),
        patch("kulshan.session.create_session") as create_session,
    ):
        result = CliRunner().invoke(main, ["preflight"])

    assert result.exception is marker
