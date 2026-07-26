from unittest.mock import Mock, patch

from kulshan.repl import run_aws_login


def test_run_aws_login_passes_arguments_without_a_shell() -> None:
    completed = Mock(returncode=0)
    with patch("kulshan.repl.subprocess.run", return_value=completed) as run:
        run_aws_login(["aws", "login", "--profile", "payer"])
    run.assert_called_once_with(["aws", "login", "--profile", "payer"], check=False)


def test_run_aws_login_reports_missing_cli(capsys) -> None:
    with patch("kulshan.repl.subprocess.run", side_effect=FileNotFoundError):
        run_aws_login(["aws", "login"])
    assert "AWS CLI not found" in capsys.readouterr().out
