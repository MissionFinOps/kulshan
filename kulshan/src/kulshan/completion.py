"""Shell completion support for the Kulshan CLI.

Provides AWS profile tab completion, shell completion script generation,
and the ``setup-completion`` subcommand that prints activation instructions
for bash, zsh, fish, and powershell.
"""

from __future__ import annotations

import configparser
import os
from pathlib import Path

import click
from click.shell_completion import CompletionItem


def get_aws_profiles() -> list[str]:
    """Parse ``~/.aws/config`` and ``~/.aws/credentials`` to extract profile names.

    Reads ``[profile X]`` sections from the config file (stripping the
    ``profile `` prefix; the ``[default]`` section becomes ``"default"``)
    and plain ``[X]`` sections from the credentials file.

    Returns a deduplicated, sorted list of profile name strings.
    Returns an empty list if the files do not exist or are unreadable.
    """
    profiles: set[str] = set()

    aws_dir = Path.home() / ".aws"

    # Parse ~/.aws/config
    config_path = aws_dir / "config"
    if config_path.is_file():
        parser = configparser.ConfigParser()
        try:
            parser.read(str(config_path))
            for section in parser.sections():
                if section.startswith("profile "):
                    profiles.add(section[len("profile "):])
                elif section == "default":
                    profiles.add("default")
        except (configparser.Error, OSError):
            pass

    # Parse ~/.aws/credentials
    credentials_path = aws_dir / "credentials"
    if credentials_path.is_file():
        parser = configparser.ConfigParser()
        try:
            parser.read(str(credentials_path))
            for section in parser.sections():
                profiles.add(section)
        except (configparser.Error, OSError):
            pass

    return sorted(profiles)


class AWSProfileType(click.ParamType):
    """Custom Click parameter type that provides AWS profile tab completion."""

    name = "aws_profile"

    def shell_complete(
        self, ctx: click.Context, param: click.Parameter, incomplete: str
    ) -> list[CompletionItem]:
        """Return matching AWS CLI profile names for shell tab completion."""
        profiles = get_aws_profiles()
        return [
            CompletionItem(p) for p in profiles if p.startswith(incomplete)
        ]

    def convert(
        self, value: str, param: click.Parameter | None, ctx: click.Context | None
    ) -> str:
        """Pass through -- validation happens at boto3 session creation time."""
        return value


def generate_completion_script(prog_name: str, shell: str) -> str:
    """Generate the shell completion activation script.

    Args:
        prog_name: The CLI program name (e.g. ``"Kulshan"``).
        shell: One of ``"bash"``, ``"zsh"``, ``"fish"``, or ``"powershell"``.

    Returns:
        A string containing the completion script with a comment header
        explaining how to persist the completion in the user's shell config.
    """
    env_var = f"_{prog_name.upper().replace('-', '_')}_COMPLETE"

    if shell == "bash":
        return (
            f"# Kulshan Shell completion for bash\n"
            f"# Add the following line to your ~/.bashrc to enable permanently:\n"
            f"#   eval \"$({env_var}=bash_source {prog_name})\"\n"
            f"\n"
            f'eval "$({env_var}=bash_source {prog_name})"'
        )

    if shell == "zsh":
        return (
            f"# Kulshan Shell completion for zsh\n"
            f"# Add the following line to your ~/.zshrc to enable permanently:\n"
            f"#   eval \"$({env_var}=zsh_source {prog_name})\"\n"
            f"\n"
            f'eval "$({env_var}=zsh_source {prog_name})"'
        )

    if shell == "fish":
        return (
            f"# Kulshan Shell completion for fish\n"
            f"# Add the following line to ~/.config/fish/completions/{prog_name}.fish\n"
            f"# to enable permanently:\n"
            f"#   {env_var}=fish_source {prog_name} | source\n"
            f"\n"
            f"{env_var}=fish_source {prog_name} | source"
        )

    # powershell
    return (
        f"# Kulshan Shell completion for PowerShell\n"
        f"# Add the following to your PowerShell profile ($PROFILE) to enable permanently:\n"
        f"#   {env_var}=powershell_source {prog_name} | Invoke-Expression\n"
        f"\n"
        f"{env_var}=powershell_source {prog_name} | Invoke-Expression"
    )


def make_setup_completion_command(prog_name: str) -> click.Command:
    """Create a ``setup-completion`` Click command.

    The command auto-detects the user's shell from the ``$SHELL`` environment
    variable and supports a ``--shell`` override. It prints the completion
    activation script to stdout.

    Args:
        prog_name: The CLI program name (e.g. ``"Kulshan"``).

    Returns:
        A Click command ready to be registered on a group.
    """

    @click.command("setup-completion", help="Print shell completion script for Kulshan.")
    @click.option(
        "--shell",
        "shell_name",
        type=click.Choice(["bash", "zsh", "fish", "powershell"]),
        default=None,
        help="Shell type. Auto-detected from $SHELL if not provided.",
    )
    def setup_completion(shell_name: str | None) -> None:
        if shell_name is None:
            shell_env = os.environ.get("SHELL", "")
            detected = os.path.basename(shell_env) if shell_env else ""
            if detected in ("bash", "zsh", "fish"):
                shell_name = detected
            elif detected in ("pwsh", "powershell"):
                shell_name = "powershell"
            else:
                shell_name = "bash"
                click.echo(
                    f"Warning: could not detect shell from $SHELL={shell_env!r}, "
                    f"defaulting to bash.",
                    err=True,
                )

        script = generate_completion_script(prog_name, shell_name)
        click.echo(script)

    return setup_completion
