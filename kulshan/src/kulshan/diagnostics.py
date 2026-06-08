"""Miette-style diagnostic rendering for Kulshan errors.

Provides rich, actionable error messages with visual context, help text,
and suggested fixes. Uses Rich panels and syntax highlighting.
"""
from __future__ import annotations

from typing import Optional

from rich.console import Console
from rich.panel import Panel
from rich.syntax import Syntax
from rich.text import Text


class Diagnostic:
    """A structured error diagnostic with context and help."""

    def __init__(
        self,
        title: str,
        message: str,
        *,
        help_text: Optional[str] = None,
        code_context: Optional[str] = None,
        code_language: str = "toml",
        error_line: Optional[int] = None,
        source_file: Optional[str] = None,
        severity: str = "error",  # error, warning, info
    ):
        self.title = title
        self.message = message
        self.help_text = help_text
        self.code_context = code_context
        self.code_language = code_language
        self.error_line = error_line
        self.source_file = source_file
        self.severity = severity

    def render(self, console: Optional[Console] = None) -> None:
        """Render the diagnostic to the console."""
        if console is None:
            console = Console(stderr=True)

        # Severity styling
        severity_styles = {
            "error": ("red", "✗"),
            "warning": ("yellow", "⚠"),
            "info": ("blue", "ℹ"),
        }
        color, icon = severity_styles.get(self.severity, ("red", "✗"))

        # Title line
        console.print()
        console.print(f"  [{color} bold]{icon} {self.title}[/{color} bold]")
        console.print()

        # Source file reference
        if self.source_file:
            loc = self.source_file
            if self.error_line:
                loc += f":{self.error_line}"
            console.print(f"  [dim]╭─[/dim] {loc}")

        # Code context with highlighting
        if self.code_context:
            console.print(f"  [dim]│[/dim]")
            syntax = Syntax(
                self.code_context,
                self.code_language,
                line_numbers=True,
                start_line=max(1, (self.error_line or 1) - 2),
                highlight_lines={self.error_line} if self.error_line else set(),
                theme="monokai",
            )
            # Indent the syntax block
            for line in syntax.__rich_console__(console, console.options):
                console.print(f"  [dim]│[/dim] ", end="")
                console.print(line)
            console.print(f"  [dim]│[/dim]")

        # Error message
        console.print(f"  [{color}]{self.message}[/{color}]")

        # Help text
        if self.help_text:
            console.print()
            console.print(f"  [bold]Help:[/bold] {self.help_text}")

        console.print()


# ---------------------------------------------------------------------------
# Pre-built diagnostics for common errors
# ---------------------------------------------------------------------------

def credential_expired(profile: Optional[str] = None) -> Diagnostic:
    """Diagnostic for expired AWS credentials."""
    help_cmd = f"aws sso login --profile {profile}" if profile else "aws sso login"
    return Diagnostic(
        title="AWS credentials expired",
        message="Your AWS session token has expired. The scan cannot authenticate.",
        help_text=f"Run: [bold green]{help_cmd}[/bold green]",
        severity="error",
    )


def no_credentials() -> Diagnostic:
    """Diagnostic for missing AWS credentials."""
    return Diagnostic(
        title="No AWS credentials found",
        message="Kulshan could not locate any AWS credentials on this machine.",
        help_text=(
            "Configure credentials using one of:\n"
            "  • [green]aws configure[/green] (interactive setup)\n"
            "  • Export [green]AWS_ACCESS_KEY_ID[/green] and [green]AWS_SECRET_ACCESS_KEY[/green]\n"
            "  • [green]aws sso login --profile your-profile[/green]"
        ),
        severity="error",
    )


def config_parse_error(
    file_path: str,
    line: int,
    key: str,
    message: str,
    code_snippet: str = "",
) -> Diagnostic:
    """Diagnostic for TOML config file parse errors."""
    return Diagnostic(
        title=f"Invalid configuration: {key}",
        message=message,
        help_text=f"Check the value of [bold]{key}[/bold] in your config file.",
        code_context=code_snippet,
        code_language="toml",
        error_line=line,
        source_file=file_path,
        severity="error",
    )


def permission_denied(service: str, action: str, region: str) -> Diagnostic:
    """Diagnostic for AWS AccessDenied errors."""
    return Diagnostic(
        title=f"Permission denied: {service}:{action}",
        message=f"AccessDenied when calling {action} in {region}.",
        help_text=(
            "Attach the Kulshan IAM policy to your role/user:\n"
            "  • [green]kulshan/iam/kulshan-readonly.json[/green] (all packs)\n"
            "  • Or attach AWS managed policies: [green]ViewOnlyAccess + SecurityAudit[/green]"
        ),
        severity="warning",
    )


def cost_explorer_not_enabled() -> Diagnostic:
    """Diagnostic for Cost Explorer not being enabled."""
    return Diagnostic(
        title="Cost Explorer not enabled",
        message="The Cost Explorer API has not been activated for this account.",
        help_text=(
            "Enable it in the AWS Console:\n"
            "  1. Go to [green]Billing → Cost Explorer[/green]\n"
            "  2. Click [green]Enable Cost Explorer[/green]\n"
            "  3. Wait 24 hours for data to populate\n\n"
            "The cost pack will show 0 findings until data is available."
        ),
        severity="warning",
    )


def rate_limited(service: str, wait_seconds: float) -> Diagnostic:
    """Diagnostic for API rate limiting."""
    return Diagnostic(
        title=f"Rate limited by {service}",
        message=f"AWS is throttling requests. Backing off for {wait_seconds:.0f}s...",
        help_text="This is normal for large accounts. Kulshan will retry automatically.",
        severity="info",
    )


def module_not_found(module: str, install_cmd: str) -> Diagnostic:
    """Diagnostic for missing optional dependencies."""
    return Diagnostic(
        title=f"Optional module not found: {module}",
        message=f"The '{module}' package is not installed.",
        help_text=f"Install it with: [bold green]{install_cmd}[/bold green]",
        severity="error",
    )
