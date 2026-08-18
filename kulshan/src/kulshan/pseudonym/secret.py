"""Workspace pseudonymization secret management.

The secret is a 32-byte cryptographically random value stored in the
workspace data directory. It is created once and never modified.

Security properties:
- Generated from os.urandom (CSPRNG)
- Created atomically (O_CREAT | O_EXCL prevents race conditions)
- File permissions set to 0o600 (owner read/write only)
- Never exported, logged, or included in any output
- Corruption fails closed (no silent regeneration)
"""
from __future__ import annotations

import os
from contextlib import suppress
from pathlib import Path

SECRET_FILENAME = "pseudonym.key"
SECRET_LENGTH = 32


class SecretCorruptError(Exception):
    """The workspace pseudonymization secret is corrupt or invalid."""

    def __init__(self, path: Path):
        self.path = path
        super().__init__(
            f"Workspace pseudonymization secret is corrupt: {path}\n"
            f"File exists but is not {SECRET_LENGTH} bytes.\n"
            f"To reset (this will change all future aliases): delete the file and re-run."
        )


class SecretCreationError(Exception):
    """Could not create the workspace pseudonymization secret."""

    def __init__(self, path: Path, cause: Exception):
        self.path = path
        self.cause = cause
        super().__init__(
            f"Could not create pseudonymization secret at {path}: {cause}"
        )


def load_or_create_secret(workspace_path: Path) -> bytes:
    """Load the workspace secret, creating it atomically if absent.

    Args:
        workspace_path: Path to the workspace data directory.

    Returns:
        32-byte secret.

    Raises:
        SecretCorruptError: If the file exists but is not exactly 32 bytes.
        SecretCreationError: If the file cannot be created.
    """
    secret_path = workspace_path / SECRET_FILENAME

    # Try to read existing secret
    if secret_path.exists():
        data = secret_path.read_bytes()
        if len(data) != SECRET_LENGTH:
            raise SecretCorruptError(secret_path)
        return data

    # Create new secret atomically
    return _create_secret_atomic(secret_path)


def _create_secret_atomic(secret_path: Path) -> bytes:
    """Create a new secret file atomically using O_CREAT | O_EXCL.

    If two processes race, one gets FileExistsError and reads the winner's file.
    """
    secret_path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    secret_data = os.urandom(SECRET_LENGTH)

    try:
        # O_CREAT | O_EXCL: create exclusively, fail if exists
        # O_BINARY needed on Windows to prevent newline translation
        flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY
        if hasattr(os, "O_BINARY"):
            flags |= os.O_BINARY
        fd = os.open(
            str(secret_path),
            flags,
            0o600,
        )
        try:
            os.write(fd, secret_data)
        finally:
            os.close(fd)

        # Ensure permissions on platforms that support it
        with suppress(OSError):
            secret_path.chmod(0o600)

        return secret_data

    except FileExistsError:
        # Another process won the race. Read their file.
        data = secret_path.read_bytes()
        if len(data) != SECRET_LENGTH:
            raise SecretCorruptError(secret_path)
        return data

    except OSError as exc:
        raise SecretCreationError(secret_path, exc) from exc
