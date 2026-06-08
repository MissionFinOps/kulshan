"""Interactive ``?`` inline help for the Kulshan CLI.

Intercepts a trailing ``?`` token in ``sys.argv``, resolves the command
context by walking the Click command tree, introspects available
subcommands and options, and renders a Rich help overlay to stderr.
"""

from __future__ import annotations

import sys

import click
from rich.console import Console
from rich.panel import Panel
from rich.table import Table


def intercept_question_mark(
    group: click.Group,
    tool_name: str,
    theme: str,
) -> None:
    """Check ``sys.argv`` for a trailing ``?`` token and display contextual help.

    Only a standalone trailing ``?`` token triggers help. If ``?`` appears
    embedded within another argument (e.g. ``--profile foo?bar``), it is
    ignored.

    When triggered, this function resolves the command context from the
    preceding tokens, gathers completions, renders the help overlay to
    stderr, and exits with code 0.

    If no trailing ``?`` is found, returns immediately (no-op).
    """
    argv = sys.argv[1:]  # skip program name

    if not argv or argv[-1] != "?":
        return

    # Tokens between program name and the trailing "?"
    tokens = argv[:-1]

    command, incomplete = resolve_context(group, tokens)
    completions = get_completions(command, incomplete)

    # Build a context label from the tokens typed so far
    parts = [tool_name] + tokens
    if incomplete:
        parts = parts[:-1]  # drop the incomplete fragment from the label
    context_label = " ".join(parts) if parts else tool_name

    render_help_overlay(completions, tool_name, theme, context_label)
    sys.exit(0)


def resolve_context(
    group: click.Group,
    tokens: list[str],
) -> tuple[click.BaseCommand, str]:
    """Walk the Click command tree to find the deepest matching command.

    Starting at *group*, each token is checked against the current
    command's subcommands. If it matches, we descend into that
    subcommand and continue with the remaining tokens. If it does not
    match (or there are no more tokens), we return the current command
    and the remaining text as an incomplete prefix.

    Handles Kulshan's three-level nesting:
      - Level 0: Kulshan main group
      - Level 1: tool subcommand groups (sweep, cost, tag, ...)
      - Level 2: tool's own subcommands (scan, report, ...)

    Returns:
        A tuple of ``(command, incomplete_prefix)`` where *command* is
        the resolved Click command/group and *incomplete_prefix* is the
        partial text the user has started typing (empty string if the
        last token was a complete subcommand match).
    """
    current: click.BaseCommand = group

    for i, token in enumerate(tokens):
        # Check if the current command is a group with subcommands
        if not hasattr(current, "commands") and not hasattr(current, "list_commands"):
            # Not a group, so remaining tokens form the incomplete prefix
            return current, token

        # Get available subcommand names
        sub_names = _get_subcommand_names(current)

        if token in sub_names:
            # Descend into the matched subcommand
            if hasattr(current, "commands") and token in current.commands:
                current = current.commands[token]
            else:
                # Use get_command as fallback
                ctx = click.Context(current, info_name=token)
                sub_cmd = current.get_command(ctx, token)  # type: ignore[union-attr]
                if sub_cmd is not None:
                    current = sub_cmd
                else:
                    return current, token
        else:
            # Token does not match any subcommand; treat it as incomplete prefix
            return current, token

    # All tokens consumed; no incomplete prefix
    return current, ""


def get_completions(
    command: click.BaseCommand,
    incomplete: str,
) -> list[dict]:
    """Introspect a Click command to produce completion candidates.

    If *command* is a Group, its subcommands are listed. All non-hidden
    options are also listed. Results are filtered by *incomplete* prefix
    when non-empty.

    Returns:
        A list of dicts with keys ``name``, ``help``, and ``type``
        (either ``"command"`` or ``"option"``), sorted by name.
    """
    candidates: list[dict] = []

    # Subcommands (if the command is a group)
    if hasattr(command, "commands") or hasattr(command, "list_commands"):
        sub_names = _get_subcommand_names(command)
        for name in sub_names:
            sub_cmd = _get_subcommand(command, name)
            if sub_cmd is None:
                continue
            help_text = sub_cmd.get_short_help_str() if sub_cmd else ""
            candidates.append({
                "name": name,
                "help": help_text,
                "type": "command",
            })

    # Options (non-hidden)
    if hasattr(command, "params"):
        for param in command.params:
            if isinstance(param, click.Option) and not param.hidden:
                # Prefer the long-form option name
                opt_name = param.opts[-1] if param.opts else ""
                for opt in param.opts:
                    if opt.startswith("--"):
                        opt_name = opt
                        break
                candidates.append({
                    "name": opt_name,
                    "help": param.help or "",
                    "type": "option",
                })

    # Filter by incomplete prefix
    if incomplete:
        candidates = [c for c in candidates if c["name"].startswith(incomplete)]

    # Sort by name
    candidates.sort(key=lambda c: c["name"])
    return candidates


def render_help_overlay(
    completions: list[dict],
    tool_name: str,
    theme: str,
    context_label: str,
) -> None:
    """Render completions as a Rich panel to stderr.

    Uses purple accent for the panel border and header. Names are styled
    in purple/accent color with aligned columns for descriptions.

    If *completions* is empty, shows a panel with "No matches" in dim text.
    """
    from kulshan.theme import get_theme

    resolved_theme = get_theme(theme)
    console = Console(stderr=True)

    if not completions:
        panel = Panel(
            "[dim]No matches[/dim]",
            border_style="purple",
            title=f"[bold]{context_label}[/bold]",
            expand=False,
        )
        console.print(panel)
        return

    table = Table(show_header=False, box=None, padding=(0, 2))
    table.add_column("name", style=resolved_theme.accent, no_wrap=True)
    table.add_column("description")

    for entry in completions:
        table.add_row(entry["name"], entry["help"])

    panel = Panel(
        table,
        border_style="purple",
        title=f"[bold]{context_label}[/bold]",
        expand=False,
    )
    console.print(panel)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _get_subcommand_names(group: click.BaseCommand) -> list[str]:
    """Return the list of subcommand names for a group-like command."""
    if hasattr(group, "commands"):
        return list(group.commands.keys())  # type: ignore[union-attr]
    if hasattr(group, "list_commands"):
        ctx = click.Context(group)
        return group.list_commands(ctx)  # type: ignore[union-attr]
    return []


def _get_subcommand(
    group: click.BaseCommand,
    name: str,
) -> click.BaseCommand | None:
    """Retrieve a subcommand by name from a group-like command."""
    if hasattr(group, "commands"):
        return group.commands.get(name)  # type: ignore[union-attr]
    if hasattr(group, "get_command"):
        ctx = click.Context(group)
        return group.get_command(ctx, name)  # type: ignore[union-attr]
    return None
