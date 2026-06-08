"""Rich help formatting for the Kulshan CLI suite.

Provides a ``patch_for_rich_help`` function that adds a purple-accented
"Mission FinOps" footer to every ``--help`` page without breaking
rich-click's internal state.

Instead of swapping ``__class__`` (which skips ``RichGroup.__init__`` and
causes missing-attribute errors), we monkey-patch ``format_help`` on
existing Click command instances.
"""

from __future__ import annotations

from functools import wraps
from typing import Any

import click
from rich.console import Console


def _make_footer_format_help(original_format_help: Any) -> Any:
    """Wrap an existing ``format_help`` method to append the Mission FinOps footer."""

    @wraps(original_format_help)
    def format_help(self: Any, ctx: click.Context, formatter: click.HelpFormatter) -> None:
        original_format_help(ctx, formatter)
        console = Console(stderr=True)
        console.print("[purple]Mission FinOps[/purple] \U0001f984", justify="center")

    return format_help


def patch_for_rich_help(group: click.Group) -> None:
    """Patch a Click group (and its subcommands) to show a themed footer on --help.

    This approach monkey-patches ``format_help`` on each command instance
    rather than swapping ``__class__``, which avoids missing-attribute
    errors with rich-click.

    Args:
        group: The Click group to patch. All registered subcommands
            (including nested groups) are patched recursively.
    """
    _patch_command(group)

    for cmd in group.commands.values():
        if isinstance(cmd, click.Group):
            patch_for_rich_help(cmd)  # recurse into nested groups
        elif isinstance(cmd, click.Command):
            _patch_command(cmd)


def _patch_command(cmd: click.BaseCommand) -> None:
    """Patch a single command's format_help to append the footer."""
    original = cmd.format_help
    # Avoid double-patching
    if getattr(original, "_finops_patched", False):
        return

    def patched_format_help(ctx: click.Context, formatter: click.HelpFormatter) -> None:
        original(ctx, formatter)
        console = Console(stderr=True)
        console.print("[purple]Mission FinOps[/purple] \U0001f984", justify="center")

    patched_format_help._finops_patched = True  # type: ignore[attr-defined]
    cmd.format_help = patched_format_help  # type: ignore[assignment]
