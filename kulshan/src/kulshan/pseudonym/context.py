"""Workspace-aware pseudonymization context resolution.

Resolves the active workspace path for secret storage, ensuring that
each workspace owns its own pseudonym.key and aliases are scoped to
workspace identity.

Invariant:
    Same raw identifier + workspace A secret -> alias A
    Same raw identifier + workspace B secret -> DIFFERENT alias B
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from kulshan.pseudonym.engine import PseudonymizationEngine
from kulshan.pseudonym.policy import PseudonymPolicy


def resolve_workspace_secret_path() -> Path:
    """Resolve the active workspace directory for pseudonym secret storage.

    Resolution follows the standard workspace resolution order:
    1. KULSHAN_WORKSPACE environment variable
    2. Saved active workspace from config.toml
    3. "default" workspace

    Returns the workspace DATA DIRECTORY (not workspaces root, not data_dir root).

    Raises:
        RuntimeError: If no workspace can be resolved.
    """
    from kulshan.workspace.resolution import resolve_workspace

    try:
        ctx = resolve_workspace()
        return ctx.path
    except Exception:
        # If workspace resolution fails (no workspace infrastructure yet),
        # use the default workspace path directly
        from kulshan.workspace.paths import get_workspace_path
        default_path = get_workspace_path("default")
        default_path.mkdir(parents=True, exist_ok=True)
        return default_path


def create_engine_for_output(
    policy: Optional[PseudonymPolicy] = None,
) -> Optional[PseudonymizationEngine]:
    """Create a pseudonymization engine scoped to the active workspace.

    Returns None if workspace resolution fails (graceful degradation).
    Raises SecretCorruptError if the secret exists but is corrupt (fail-closed).

    Args:
        policy: Override policy. Defaults to structured output policy.

    Returns:
        PseudonymizationEngine or None.
    """
    from kulshan.pseudonym.secret import SecretCorruptError

    if policy is None:
        policy = PseudonymPolicy.for_structured_output()

    try:
        workspace_path = resolve_workspace_secret_path()
    except Exception:
        return None  # Graceful degradation

    try:
        return PseudonymizationEngine.create(workspace_path, policy)
    except SecretCorruptError:
        raise  # Fail closed - propagate to caller
    except Exception:
        return None  # Graceful degradation
