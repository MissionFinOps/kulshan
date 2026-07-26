"""Consent-first PyPI update checks.

This module deliberately has no AWS imports. Its public entry point is called
from the root CLI callback before workspace discovery or credential handling.
"""

from __future__ import annotations

import sys
from datetime import date
from typing import TextIO

import click
import httpx
from packaging.version import InvalidVersion, Version

PYPI_URL = "https://pypi.org/pypi/kulshan/json"
UPDATE_COMMAND = "python -m pip install --upgrade kulshan"


def release_age_text(release_date: str, today: date | None = None) -> str:
    """Describe the age of a release using only local date information."""
    released = date.fromisoformat(release_date)
    age_days = ((today or date.today()) - released).days
    if age_days <= 0:
        return "released today"
    if age_days == 1:
        return "released 1 day ago"
    return f"released {age_days} days ago"


def fetch_latest_version(current_version: str) -> str:
    """Fetch the latest Kulshan version from PyPI after user consent."""
    response = httpx.get(
        PYPI_URL,
        timeout=3.0,
        follow_redirects=True,
        headers={"User-Agent": f"kulshan/{current_version} update-check"},
    )
    response.raise_for_status()
    return str(response.json()["info"]["version"])


def prompt_for_update_check(
    current_version: str,
    release_date: str,
    *,
    stdin: TextIO | None = None,
    stderr: TextIO | None = None,
) -> None:
    """Offer a disclosed PyPI check before any AWS-related startup work.

    Non-interactive processes are left untouched. The default response is No,
    consent is never persisted, and network failures never block execution.
    """
    input_stream = stdin or sys.stdin
    error_stream = stderr or sys.stderr
    if not input_stream.isatty():
        return

    try:
        released = date.fromisoformat(release_date)
        date_label = f"{released.strftime('%B')} {released.day}, {released.year}"
        release_summary = f"{date_label} ? {release_age_text(release_date)}"
    except ValueError:
        release_summary = "release date unknown"

    click.echo(
        f"\nKulshan {current_version}: {release_summary}.",
        file=error_stream,
    )
    click.echo(
        "Check PyPI for a newer version?\n"
        "This sends one HTTPS request to pypi.org. No AWS account, "
        "credentials, profile, workspace, or report data is included.",
        file=error_stream,
    )
    consent = click.confirm(
        "Check for update",
        default=False,
        err=True,
    )
    if not consent:
        return

    try:
        latest = fetch_latest_version(current_version)
        installed = Version(current_version)
        available = Version(latest)
    except (httpx.HTTPError, KeyError, TypeError, InvalidVersion, ValueError):
        click.echo(
            "Could not check PyPI. Continuing with the installed version.",
            file=error_stream,
        )
        return

    if available > installed:
        click.echo(
            f"\nKulshan {latest} is available. You have {current_version}.\n"
            f"Update with:\n  {UPDATE_COMMAND}\n",
            file=error_stream,
        )
    else:
        click.echo(
            f"Kulshan {current_version} is the latest version.",
            file=error_stream,
        )
