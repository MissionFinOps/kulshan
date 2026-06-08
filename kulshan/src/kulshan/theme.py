"""Theme registry and banner rendering for the Kulshan CLI suite.

Provides per-tool color themes with a shared purple accent, and a Rich-based
banner renderer that displays tool identity with mountain flair.
"""

from __future__ import annotations

from dataclasses import dataclass

from rich.console import Console
from rich.panel import Panel


@dataclass
class ToolTheme:
    """Color configuration for Kulshan or a tool subcommand."""

    primary: str       # Main brand color
    secondary: str     # Secondary color for less prominent elements
    accent: str        # Always "purple", the shared suite accent
    highlight: str     # Color for emphasis and highlights


# ---------------------------------------------------------------------------
# Theme registry: Kulshan parent theme + all 10 tool subcommand themes
# ---------------------------------------------------------------------------

THEME_REGISTRY: dict[str, ToolTheme] = {
    # Kulshan parent theme
    "kulshan": ToolTheme(
        primary="purple", secondary="white", accent="purple", highlight="cyan",
    ),
    # Per-tool subcommand themes
    "cost": ToolTheme(
        primary="cyan", secondary="blue", accent="purple", highlight="green",
    ),
    "sweep": ToolTheme(
        primary="dark_red", secondary="red", accent="purple", highlight="yellow",
    ),
    "tag": ToolTheme(
        primary="dark_green", secondary="green", accent="purple", highlight="yellow",
    ),
    "age": ToolTheme(
        primary="dark_green", secondary="green", accent="purple", highlight="cyan",
    ),
    "dr": ToolTheme(
        primary="blue", secondary="cyan", accent="purple", highlight="red",
    ),
    "pulse": ToolTheme(
        primary="purple4", secondary="magenta", accent="purple", highlight="cyan",
    ),
    "limit": ToolTheme(
        primary="dark_orange3", secondary="yellow", accent="purple", highlight="red",
    ),
    "drift": ToolTheme(
        primary="cyan", secondary="blue", accent="purple", highlight="yellow",
    ),
    "topo": ToolTheme(
        primary="magenta", secondary="purple", accent="purple", highlight="cyan",
    ),
    "security": ToolTheme(
        primary="blue", secondary="cyan", accent="purple", highlight="green",
    ),
}


def get_theme(name: str) -> ToolTheme:
    """Look up a theme by Kulshan subcommand name.

    Falls back to the Kulshan parent theme if the name is not found.
    """
    return THEME_REGISTRY.get(name, THEME_REGISTRY["kulshan"])


def render_banner(
    tool_name: str,
    tagline: str,
    version: str,
    theme: ToolTheme,
) -> None:
    """Print a themed banner to the console.

    Displays a Rich Panel with:
    - Purple accent border
    - Tool name in bold white with a single mountain emoji
    - Tagline in dim text
    - Version in dim text
    """
    console = Console()
    content = (
        f"[bold white]{tool_name}[/bold white] \U0001f984  "
        f"[dim]{tagline}[/dim]\n"
        f"[dim]{version}[/dim]"
    )
    panel = Panel(content, style="purple", expand=False)
    console.print(panel)
