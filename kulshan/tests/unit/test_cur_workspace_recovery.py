from types import SimpleNamespace
from unittest.mock import Mock, patch

import kulshan.workspace.onboarding as onboarding_module
import kulshan.workspace.resolution as resolution_module
from kulshan.cur.cli_commands import _workspace


def _context(*, workspace=None, profile=None, role_arn=None):
    root = SimpleNamespace(
        obj={"workspace": workspace, "profile": profile, "role_arn": role_arn}
    )
    return SimpleNamespace(find_root=lambda: root)


def test_cur_workspace_auto_onboards_when_active_workspace_is_stale() -> None:
    recovered = object()
    onboarding = Mock(workspace_context=recovered)
    with (
        patch.object(
            resolution_module,
            "resolve_workspace_with_profile",
            return_value=None,
        ) as resolve,
        patch.object(
            onboarding_module,
            "auto_onboard",
            return_value=onboarding,
        ) as onboard,
    ):
        result = _workspace(_context())
    assert result is recovered
    resolve.assert_called_once_with(profile=None, role_arn=None)
    onboard.assert_called_once_with(profile=None, role_arn=None)


def test_cur_workspace_keeps_explicit_workspace_strict() -> None:
    explicit = object()
    with patch.object(
        resolution_module,
        "resolve_workspace",
        return_value=explicit,
    ) as resolve:
        result = _workspace(_context(workspace="payer-prod"))
    assert result is explicit
    resolve.assert_called_once_with("payer-prod")
