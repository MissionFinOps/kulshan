"""
Shared test fixtures for the Kulshan test suite.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

import pytest

FIXTURES_DIR = Path(__file__).parent / "fixtures"


@pytest.fixture
def fixtures_dir() -> Path:
    """Path to the test fixtures directory."""
    return FIXTURES_DIR


import click
from io import StringIO

from rich.console import Console


@pytest.fixture
def mock_aws_config(tmp_path):
    """Create mock ~/.aws/config and ~/.aws/credentials files in a temp directory.

    Returns a dict with keys ``config_path``, ``credentials_path``, and
    ``profiles`` (the list of profile names written).
    """
    aws_dir = tmp_path / ".aws"
    aws_dir.mkdir()

    profiles = ["default", "dev", "prod"]

    # Write ~/.aws/config
    config_path = aws_dir / "config"
    config_lines = ["[default]\nregion = us-east-1\n"]
    for name in profiles:
        if name != "default":
            config_lines.append(f"[profile {name}]\nregion = us-west-2\n")
    config_path.write_text("\n".join(config_lines))

    # Write ~/.aws/credentials
    credentials_path = aws_dir / "credentials"
    cred_lines = []
    for name in profiles:
        cred_lines.append(
            f"[{name}]\n"
            f"aws_access_key_id = FAKE{name.upper()}KEY\n"
            f"aws_secret_access_key = FAKE{name.upper()}SECRET\n"
        )
    credentials_path.write_text("\n".join(cred_lines))

    return {
        "config_path": config_path,
        "credentials_path": credentials_path,
        "profiles": profiles,
    }


@pytest.fixture
def simple_click_group():
    """Create a Click group with 3 subcommands: scan, report, fix.

    Each subcommand has a few options (--profile, --output, --quick).
    Returns the group.
    """

    @click.group("Kulshan")
    def group():
        """A simple test CLI group."""

    @group.command()
    @click.option("--profile", help="AWS profile to use.")
    @click.option("--output", "-o", help="Output file path.")
    def scan(profile, output):
        """Scan AWS resources."""

    @group.command()
    @click.option("--profile", help="AWS profile to use.")
    @click.option("--output", "-o", help="Output file path.")
    def report(profile, output):
        """Generate a report."""

    @group.command()
    @click.option("--profile", help="AWS profile to use.")
    @click.option("--quick", is_flag=True, help="Run in quick mode.")
    def fix(profile, quick):
        """Apply fixes."""

    return group


@pytest.fixture
def nested_click_group():
    """Create a Click group that mimics Kulshan's nested structure.

    A main group with 2 tool subcommand groups (sweep and cost), each
    having their own subcommands. Returns the group.
    """

    @click.group("Kulshan")
    def main_group():
        """Kulshan-like nested CLI group."""

    @main_group.group("sweep")
    def sweep_group():
        """Sweep tool group."""

    @sweep_group.command("scan")
    @click.option("--profile", help="AWS profile to use.")
    @click.option("--regions", help="AWS regions to scan.")
    def sweep_scan(profile, regions):
        """Scan for unused resources."""

    @sweep_group.command("report")
    @click.option("--output", "-o", help="Output file path.")
    def sweep_report(output):
        """Generate sweep report."""

    @main_group.group("cost")
    def cost_group():
        """Cost tool group."""

    @cost_group.command("analyze")
    @click.option("--profile", help="AWS profile to use.")
    @click.option("--days", type=int, default=30, help="Number of days to analyze.")
    def cost_analyze(profile, days):
        """Analyze AWS costs."""

    @cost_group.command("report")
    @click.option("--output", "-o", help="Output file path.")
    @click.option("--format", "fmt", type=click.Choice(["json", "csv", "html"]), help="Report format.")
    def cost_report(output, fmt):
        """Generate cost report."""

    return main_group


@pytest.fixture
def capture_rich_output():
    """Return a helper function that captures Rich Console output to a string.

    Usage::

        def test_something(capture_rich_output):
            console, get_output = capture_rich_output()
            console.print("[bold]hello[/bold]")
            text = get_output()
            assert "hello" in text
    """

    def _factory():
        buf = StringIO()
        console = Console(file=buf, force_terminal=True)

        def get_output() -> str:
            return buf.getvalue()

        return console, get_output

    return _factory
