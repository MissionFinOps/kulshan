"""AWS execution context resolution for workspaces.

Resolves the correct AWS session for a workspace command based on
connection configuration, CLI arguments, and STS verification.

This is the single authoritative implementation for runtime credential
resolution. Both workspace creation (sts.py) and runtime execution
share the same STS verification path.
"""
from __future__ import annotations

import logging
import sys
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import boto3

from kulshan.workspace.config import AwsConnection
from kulshan.workspace.context import WorkspaceContext
from kulshan.workspace.errors import (
    AmbiguousProfileError,
    ConnectionConflictError,
    ConnectionNotFoundError,
    ProfileNotConfiguredError,
    RoleArnConflictError,
    WorkspaceCredentialMismatchError,
)
from kulshan.workspace.sts import (
    StsVerificationError,
    StsVerificationResult,
    verify_credentials,
)

logger = logging.getLogger(__name__)

# Track whether unbound warning has been shown this process
_unbound_warning_shown: bool = False


@dataclass
class AwsExecutionContext:
    """Resolved AWS execution context for a workspace command."""

    workspace: WorkspaceContext
    connection: AwsConnection | None
    session: "boto3.Session"
    resolved_profile: str | None
    session_account_id: str
    payer_account_id: str | None


def resolve_aws_execution(
    workspace: WorkspaceContext,
    connection_name: str | None = None,
    profile: str | None = None,
    role_arn: str | None = None,
    show_pii: bool = False,
) -> AwsExecutionContext:
    """
    Resolve AWS execution context for a workspace.

    For bound workspaces:
      1. Resolve connection (--connection > --profile > default_connection)
      2. Validate --role-arn against connection config
      3. Create session, assume role, call STS
      4. Validate returned account matches expected_session_account_id

    For unbound default:
      1. Use --profile or AWS_PROFILE or default chain
      2. Allow --role-arn freely
      3. Show unbound warning once

    Args:
        workspace: Resolved workspace context.
        connection_name: Explicit --connection selector.
        profile: Explicit --profile selector.
        role_arn: Explicit --role-arn.
        show_pii: Whether to show full account IDs in errors.

    Returns:
        AwsExecutionContext with the verified session.

    Raises:
        ConnectionNotFoundError: Unknown --connection.
        ProfileNotConfiguredError: --profile not in workspace.
        AmbiguousProfileError: Profile matches multiple connections.
        ConnectionConflictError: --connection and --profile conflict.
        RoleArnConflictError: --role-arn conflicts with connection.
        WorkspaceCredentialMismatchError: STS account != expected.
        StsVerificationError: STS call failed.
    """
    if workspace.is_bound:
        return _resolve_bound(
            workspace, connection_name, profile, role_arn, show_pii
        )
    else:
        return _resolve_unbound(
            workspace, profile, role_arn
        )


def _resolve_bound(
    workspace: WorkspaceContext,
    connection_name: str | None,
    profile: str | None,
    role_arn: str | None,
    show_pii: bool,
) -> AwsExecutionContext:
    """Resolve execution for a bound workspace."""
    import boto3

    aws_config = workspace.config.aws
    assert aws_config is not None  # guaranteed by is_bound

    # --- Step 1: Resolve connection ---
    connection: AwsConnection | None = None

    if connection_name and profile:
        # Both supplied — must identify the same connection
        conn_by_name = aws_config.get_connection(connection_name)
        if conn_by_name is None:
            raise ConnectionNotFoundError(workspace.name, connection_name)
        if conn_by_name.profile != profile:
            raise ConnectionConflictError(
                workspace.name, connection_name, profile, conn_by_name.profile
            )
        connection = conn_by_name

    elif connection_name:
        connection = aws_config.get_connection(connection_name)
        if connection is None:
            raise ConnectionNotFoundError(workspace.name, connection_name)

    elif profile:
        # Lookup by profile — may be ambiguous
        connection = aws_config.get_connection_by_profile(profile)
        if connection is None:
            available = [c.profile for c in aws_config.connections]
            raise ProfileNotConfiguredError(workspace.name, profile, available)

    else:
        # Use default connection
        connection = aws_config.get_connection(aws_config.default_connection)
        if connection is None:
            raise ConnectionNotFoundError(
                workspace.name, aws_config.default_connection
            )

    # --- Step 2: Validate role_arn ---
    effective_role = connection.role_arn

    if role_arn:
        if connection.role_arn is None:
            # Connection has no role, user supplied one — reject
            raise RoleArnConflictError(
                workspace.name, connection.name, None, role_arn
            )
        if role_arn != connection.role_arn:
            # Supplied role differs from configured — reject
            raise RoleArnConflictError(
                workspace.name, connection.name, connection.role_arn, role_arn
            )
        # Matches — allowed (effective_role already correct)

    # --- Step 3: Create session and verify ---
    sts_result = verify_credentials(
        profile=connection.profile,
        role_arn=effective_role,
    )

    # --- Step 4: Validate account ---
    if sts_result.account_id != connection.expected_session_account_id:
        raise WorkspaceCredentialMismatchError(
            workspace_name=workspace.name,
            connection_name=connection.name,
            profile=connection.profile,
            expected_account=connection.expected_session_account_id,
            actual_account=sts_result.account_id,
        )

    # Build the final session for use by commands
    session = _build_session(connection.profile, effective_role)

    return AwsExecutionContext(
        workspace=workspace,
        connection=connection,
        session=session,
        resolved_profile=connection.profile,
        session_account_id=sts_result.account_id,
        payer_account_id=aws_config.payer_account_id,
    )


def _resolve_unbound(
    workspace: WorkspaceContext,
    profile: str | None,
    role_arn: str | None,
) -> AwsExecutionContext:
    """Resolve execution for the unbound default workspace."""
    import os
    import boto3

    global _unbound_warning_shown
    if not _unbound_warning_shown:
        _unbound_warning_shown = True
        print(
            "Warning: Using the unbound default workspace.\n"
            "\n"
            "Runs from different AWS profiles may be stored together.\n"
            "Create a bound workspace to isolate payer data.\n",
            file=sys.stderr,
        )

    # Use --profile, or AWS_PROFILE, or default chain
    effective_profile = profile or os.environ.get("AWS_PROFILE")

    # Build session
    session = _build_session(effective_profile, role_arn)

    # Get account ID via STS
    sts_client = session.client("sts")
    identity = sts_client.get_caller_identity()
    account_id = identity["Account"]

    return AwsExecutionContext(
        workspace=workspace,
        connection=None,
        session=session,
        resolved_profile=effective_profile,
        session_account_id=account_id,
        payer_account_id=None,
    )


def _build_session(profile: str | None, role_arn: str | None) -> "boto3.Session":
    """Build a boto3 session with optional role assumption."""
    import boto3

    kwargs = {}
    if profile:
        kwargs["profile_name"] = profile
    session = boto3.Session(**kwargs)

    if role_arn:
        sts = session.client("sts")
        creds = sts.assume_role(
            RoleArn=role_arn, RoleSessionName="kulshan-exec"
        )["Credentials"]
        session = boto3.Session(
            aws_access_key_id=creds["AccessKeyId"],
            aws_secret_access_key=creds["SecretAccessKey"],
            aws_session_token=creds["SessionToken"],
        )

    return session


def _reset_unbound_warning() -> None:
    """Reset unbound warning flag. For testing only."""
    global _unbound_warning_shown
    _unbound_warning_shown = False
