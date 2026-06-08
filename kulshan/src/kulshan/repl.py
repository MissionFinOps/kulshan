"""Interactive REPL shell for the Kulshan CLI.

Provides a persistent shell session launched via ``Kulshan Shell``.
Uses ``prompt_toolkit`` for cross-platform keystroke interception,
tab completion, and command history. Reuses the existing Click command
tree for command resolution and execution.
"""

from __future__ import annotations

import shlex
import sys
from pathlib import Path
from typing import Iterable, Optional

import click
from prompt_toolkit import PromptSession
from prompt_toolkit.completion import Completer, Completion
from prompt_toolkit.document import Document
from prompt_toolkit.formatted_text import HTML
from prompt_toolkit.history import FileHistory, InMemoryHistory
from prompt_toolkit.key_binding import KeyBindings

from kulshan.__version__ import __version__ as _VERSION
from kulshan.completion import get_aws_profiles
from kulshan.question_mark import get_completions, render_help_overlay, resolve_context
from kulshan.theme import get_theme, render_banner

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

REPL_HISTORY_MAX_ENTRIES = 1000
REPL_EXIT_COMMANDS = {"exit", "quit"}
UNICODE_mountain = "\U0001f984"
ASCII_FALLBACK_PREFIX = "kulshan> "


# ---------------------------------------------------------------------------
# Utility functions
# ---------------------------------------------------------------------------


def detect_unicode_support() -> bool:
    """Check whether the current terminal supports Unicode output.

    Tests ``sys.stdout.encoding`` for UTF-8 compatibility. Returns False
    on terminals that cannot render Unicode (e.g., legacy Windows consoles
    with cp437/cp1252 encoding).
    """
    encoding = getattr(sys.stdout, "encoding", None) or ""
    return encoding.lower().replace("-", "").startswith("utf")


def get_history_path() -> Path:
    """Return the path to the REPL history file.

    Uses ``platformdirs.user_data_dir("kulshan")`` to determine the
    platform-appropriate directory. Creates the directory if it does
    not exist.
    """
    from platformdirs import user_data_dir

    data_dir = Path(user_data_dir("kulshan"))
    data_dir.mkdir(parents=True, exist_ok=True)
    return data_dir / "repl_history"


def truncate_history(history_path: Path, max_entries: int) -> None:
    """Truncate the history file to at most *max_entries* lines.

    Reads the file, keeps the last *max_entries* lines, and rewrites it.
    No-op if the file does not exist or has fewer entries than the limit.
    """
    if not history_path.is_file():
        return

    try:
        lines = history_path.read_text(encoding="utf-8").splitlines(keepends=True)
    except OSError:
        return

    if len(lines) <= max_entries:
        return

    trimmed = lines[-max_entries:]
    try:
        history_path.write_text("".join(trimmed), encoding="utf-8")
    except OSError:
        pass


def make_prompt_text(supports_unicode: bool = True) -> HTML:
    """Build the styled REPL prompt text.

    Returns an HTML-formatted prompt string with a purple-styled
    ``Kulshan>`` prefix and a mountain emoji (or ASCII fallback).
    """
    if supports_unicode:
        return HTML(
            f"{UNICODE_mountain} <style fg='purple'><b>kulshan&gt;</b></style> "
        )
    return HTML("<style fg='purple'><b>kulshan&gt;</b></style> ")


def inject_context_args(
    args: list[str],
    profile: str | None,
    role_arn: str | None,
) -> list[str]:
    """Prepend ``--profile`` and ``--role-arn`` to *args* if set.

    Skips injection for an option if the user already provided it
    explicitly in *args*.
    """
    prefix: list[str] = []
    if profile and "--profile" not in args:
        prefix.extend(["--profile", profile])
    if role_arn and "--role-arn" not in args:
        prefix.extend(["--role-arn", role_arn])
    return prefix + args


# ---------------------------------------------------------------------------
# ClickCompleter
# ---------------------------------------------------------------------------


class ClickCompleter(Completer):
    """prompt_toolkit Completer that introspects the Click command tree.

    Walks the Click group hierarchy using ``resolve_context()`` and
    ``get_completions()`` from ``Kulshan.question_mark`` to produce
    completion candidates for commands, subcommands, and options.
    Also completes AWS profile names after ``--profile``.

    Args:
        cli_group: The root Click group (Kulshan's main group).
    """

    def __init__(self, cli_group: click.Group) -> None:
        self.cli_group = cli_group

    def get_completions(
        self, document: Document, complete_event: object
    ) -> Iterable[Completion]:
        """Yield Completion objects for the current input text."""
        text = document.text_before_cursor

        try:
            tokens = shlex.split(text)
        except ValueError:
            # Incomplete quotes -- nothing useful to complete
            return

        # Determine the incomplete fragment
        if text and not text[-1].isspace():
            incomplete = tokens[-1] if tokens else ""
            completed_tokens = tokens[:-1]
        else:
            incomplete = ""
            completed_tokens = tokens

        # Special case: completing a value for --profile
        if completed_tokens and completed_tokens[-1] == "--profile":
            for name in get_aws_profiles():
                if name.startswith(incomplete):
                    yield Completion(
                        text=name,
                        start_position=-len(incomplete),
                        display_meta="AWS profile",
                    )
            return

        # Resolve the Click command context
        command, resolved_incomplete = resolve_context(self.cli_group, completed_tokens)

        # If resolve_context consumed some tokens and returned an incomplete,
        # merge it with our own incomplete tracking
        if resolved_incomplete and not incomplete:
            incomplete = resolved_incomplete

        candidates = get_completions(command, incomplete)

        for entry in candidates:
            name = entry["name"]
            # Exclude "shell" to prevent nested sessions
            if name == "shell":
                continue
            help_text = entry.get("help", "")
            yield Completion(
                text=name,
                start_position=-len(incomplete),
                display_meta=help_text,
            )


# ---------------------------------------------------------------------------
# Key bindings
# ---------------------------------------------------------------------------


def build_key_bindings(
    cli_group: click.Group,
    tool_name: str,
    theme_name: str,
) -> KeyBindings:
    """Create prompt_toolkit key bindings with a ``?`` handler.

    The ``?`` handler reads the current buffer text, resolves the Click
    command context, gathers completions, and prints the help overlay.
    It does NOT insert ``?`` into the buffer.

    Args:
        cli_group: The root Click group.
        tool_name: Display name for the help overlay header.
        theme_name: Theme name for styling the help overlay.

    Returns:
        A KeyBindings instance with the ``?`` handler registered.
    """
    kb = KeyBindings()

    @kb.add("?")
    def _question_mark_handler(event: object) -> None:  # noqa: ARG001
        buf = event.app.current_buffer  # type: ignore[union-attr]
        text = buf.text

        try:
            tokens = shlex.split(text)
        except ValueError:
            tokens = text.split()

        command, incomplete = resolve_context(cli_group, tokens)
        completions = get_completions(command, incomplete)

        parts = [tool_name] + tokens
        if incomplete:
            parts = parts[:-1]
        context_label = " ".join(parts) if parts else tool_name

        render_help_overlay(completions, tool_name, theme_name, context_label)
        # Do NOT insert '?' into the buffer

    return kb


# ---------------------------------------------------------------------------
# Main REPL loop
# ---------------------------------------------------------------------------


def run_repl(
    cli_group: click.Group,
    profile: Optional[str] = None,
    role_arn: Optional[str] = None,
) -> None:
    """Main REPL entry point.

    Displays the welcome banner, creates a ``PromptSession`` with
    ``FileHistory``, ``ClickCompleter``, and ``?`` key bindings, then
    enters the read-eval-print loop.

    Args:
        cli_group: The root Click group (Kulshan's main group).
        profile: AWS profile name from shell launch (or None).
        role_arn: IAM role ARN from shell launch (or None).
    """
    version = _VERSION
    theme = get_theme("kulshan")

    render_banner("Kulshan Shell", "Interactive REPL", version, theme)
    print("Type ? for help, Tab for completion, exit to quit")

    supports_unicode = detect_unicode_support()
    prompt_text = make_prompt_text(supports_unicode)

    # Set up persistent history
    history_path = get_history_path()
    try:
        history = FileHistory(str(history_path))
    except Exception:
        history = InMemoryHistory()

    completer = ClickCompleter(cli_group)
    kb = build_key_bindings(cli_group, "kulshan", "kulshan")

    session: PromptSession[str] = PromptSession(
        history=history,
        completer=completer,
        key_bindings=kb,
        message=prompt_text,
    )

    while True:
        try:
            text = session.prompt()
        except KeyboardInterrupt:
            continue
        except EOFError:
            break

        text = text.strip()
        if not text:
            continue

        if text.lower() in REPL_EXIT_COMMANDS:
            break

        # Nested shell prevention
        if text.split()[0].lower() == "shell":
            print("You are already in the Kulshan shell.")
            continue

        try:
            args = shlex.split(text)
        except ValueError:
            print("Error: unclosed quote in input")
            continue

        args = inject_context_args(args, profile, role_arn)

        try:
            cli_group.main(args, standalone_mode=False)
        except click.exceptions.Exit:
            pass
        except click.UsageError as e:
            print(f"Usage error: {e}")
        except click.Abort:
            print("Command aborted")
        except SystemExit:
            pass
        except KeyboardInterrupt:
            print("Command interrupted")
        except Exception as e:
            print(f"Error: {e}")

    # Session cleanup
    truncate_history(history_path, REPL_HISTORY_MAX_ENTRIES)
    if supports_unicode:
        print(f"Goodbye! {UNICODE_mountain}")
    else:
        print("Goodbye!")
