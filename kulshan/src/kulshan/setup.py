"""One-call setup that wires completion, '?' help, theming, and Rich help
formatting onto Kulshan's main Click group.

Called once in ``kulshan/src/kulshan/cli.py`` after all tool subcommands
have been registered via ``main.add_command()``.
"""

from __future__ import annotations

import click

from kulshan.completion import AWSProfileType, make_setup_completion_command
from kulshan.question_mark import intercept_question_mark


def setup_cli(
    group: click.Group,
    tool_name: str = "Kulshan",
    tagline: str = "Operations Intelligence from your terminal.",
    version: str | None = None,
    theme: str | None = None,
) -> click.Group:
    """Wire completion, ``?`` help, theming, and Rich help formatting onto *group*.

    Args:
        group: Kulshan's main Click group.
        tool_name: Display name shown in banners. Defaults to ``"Kulshan"``.
        tagline: One-line description for the banner.
        version: Version string for banner display. Auto-read from
            ``Kulshan.__version__`` if *None*.
        theme: Optional theme name override. Defaults to *tool_name*.

    Returns:
        The enhanced Click group (same object, mutated in place).

    Raises:
        TypeError: If *group* is not a :class:`click.Group` instance.
    """
    # ------------------------------------------------------------------
    # 1. Validate input
    # ------------------------------------------------------------------
    if not isinstance(group, click.Group):
        raise TypeError(
            f"setup_cli() expects a click.Group, got {type(group).__name__}"
        )

    # ------------------------------------------------------------------
    # 2. Install ? help interceptor (must run first, may sys.exit(0))
    # ------------------------------------------------------------------
    intercept_question_mark(group, tool_name, theme or tool_name)

    # ------------------------------------------------------------------
    # 3. Patch format_help for the footer on all commands
    # ------------------------------------------------------------------
    try:
        from kulshan.help_formatter import patch_for_rich_help

        patch_for_rich_help(group)
    except Exception:
        # If rich-click or the formatter has issues, degrade gracefully
        pass

    # ------------------------------------------------------------------
    # 4. Add setup-completion subcommand
    # ------------------------------------------------------------------
    completion_cmd = make_setup_completion_command("Kulshan")
    group.add_command(completion_cmd)

    # ------------------------------------------------------------------
    # 5. Replace --profile option type with AWSProfileType
    # ------------------------------------------------------------------
    for param in group.params:
        if isinstance(param, click.Option) and "--profile" in param.opts:
            param.type = AWSProfileType()

    # ------------------------------------------------------------------
    # 6. Auto-read version if not provided
    # ------------------------------------------------------------------
    if version is None:
        try:
            from kulshan.__version__ import __version__

            version = __version__
        except ImportError:
            version = "unknown"

    return group
