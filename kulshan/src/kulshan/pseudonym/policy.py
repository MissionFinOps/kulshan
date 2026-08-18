"""Pseudonymization policy controls.

Determines when and how pseudonymization is applied based on output context.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class PolicyMode(Enum):
    """Output context that determines pseudonymization behavior."""

    NORMAL = "normal"
    """Standard report output. TTY bypass allowed."""

    PERSISTENCE = "persistence"
    """Data stored at rest or sent to external clients (MCP, history).
    No TTY bypass. Always pseudonymized."""


@dataclass(frozen=True)
class PseudonymPolicy:
    """Controls pseudonymization behavior for a given output path.

    Attributes:
        mode: Output context classification.
        tty_bypass: If True and stdout is a TTY with default terminal format,
            pseudonymization is skipped (real identifiers shown).
        show_identifiers: Explicit user opt-out via --show-identifiers flag.
            When True, pseudonymization is disabled regardless of other settings.
    """

    mode: PolicyMode = PolicyMode.NORMAL
    tty_bypass: bool = True
    show_identifiers: bool = False

    @property
    def should_pseudonymize(self) -> bool:
        """Whether pseudonymization should be applied given current policy."""
        if self.show_identifiers:
            return False
        if self.mode == PolicyMode.PERSISTENCE:
            return True
        # NORMAL mode: tty_bypass controls
        return not self.tty_bypass

    @staticmethod
    def for_structured_output(show_identifiers: bool = False) -> PseudonymPolicy:
        """Policy for structured/file output (JSON, CSV, HTML, SARIF)."""
        return PseudonymPolicy(
            mode=PolicyMode.NORMAL,
            tty_bypass=False,
            show_identifiers=show_identifiers,
        )

    @staticmethod
    def for_terminal(is_tty: bool, show_identifiers: bool = False) -> PseudonymPolicy:
        """Policy for default terminal format rendering."""
        return PseudonymPolicy(
            mode=PolicyMode.NORMAL,
            tty_bypass=is_tty,
            show_identifiers=show_identifiers,
        )

    @staticmethod
    def for_persistence() -> PseudonymPolicy:
        """Policy for data stored at rest or sent externally. Never bypassed."""
        return PseudonymPolicy(
            mode=PolicyMode.PERSISTENCE,
            tty_bypass=False,
            show_identifiers=False,
        )
