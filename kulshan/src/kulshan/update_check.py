"""Consent-first, cooldown-aware PyPI update checks."""

from __future__ import annotations

import json
import os
import sys
import tempfile
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, TextIO

import click
import httpx
from packaging.version import InvalidVersion, Version

PYPI_URL = "https://pypi.org/pypi/kulshan/json"
UPDATE_COMMAND = "python -m pip install --upgrade kulshan"
UPDATE_COOLDOWN = timedelta(hours=9)
STATE_SCHEMA_VERSION = 1


def release_age_text(release_date: str, today: date | None = None) -> str:
    """Describe the age of a release using only local date information."""
    released = date.fromisoformat(release_date)
    age_days = ((today or date.today()) - released).days
    if age_days <= 0:
        return "released today"
    if age_days == 1:
        return "released 1 day ago"
    return f"released {age_days} days ago"


def get_update_state_path() -> Path:
    """Return the privacy-safe global update decision state path."""
    from kulshan.workspace.paths import get_config_dir

    return get_config_dir() / "update-check.json"


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


def _load_state(path: Path) -> dict[str, Any] | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if payload.get("schema_version") != STATE_SCHEMA_VERSION:
            return None
        return payload
    except (OSError, ValueError, TypeError):
        return None


def _state_is_fresh(state: dict[str, Any], now: datetime) -> bool:
    try:
        decided_at = datetime.fromisoformat(str(state["decided_at"]))
        if decided_at.tzinfo is None:
            decided_at = decided_at.replace(tzinfo=timezone.utc)
        decided_at = decided_at.astimezone(timezone.utc)
    except (KeyError, TypeError, ValueError):
        return False
    if decided_at > now + timedelta(minutes=5):
        return False
    return now - decided_at < UPDATE_COOLDOWN


def _save_state(path: Path, payload: dict[str, Any]) -> bool:
    try:
        path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        fd, temporary = tempfile.mkstemp(
            prefix="update-check-",
            suffix=".json.tmp",
            dir=str(path.parent),
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                json.dump(payload, stream, indent=2, sort_keys=True)
                stream.write("\n")
            os.replace(temporary, path)
        except Exception:
            try:
                os.unlink(temporary)
            except OSError:
                pass
            raise
        return True
    except OSError:
        return False


def _record_decision(
    path: Path,
    *,
    now: datetime,
    consent: bool,
    current_version: str,
    latest_version: str | None = None,
    status: str,
) -> bool:
    return _save_state(
        path,
        {
            "schema_version": STATE_SCHEMA_VERSION,
            "decided_at": now.isoformat(),
            "consent": consent,
            "installed_version": current_version,
            "latest_version": latest_version,
            "status": status,
        },
    )


def _show_result(
    current_version: str,
    latest: str,
    error_stream: TextIO,
) -> None:
    installed = Version(current_version)
    available = Version(latest)
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


def check_for_update(
    current_version: str,
    *,
    stderr: TextIO | None = None,
) -> bool:
    """Explicitly check PyPI, returning whether the request succeeded."""
    error_stream = stderr or sys.stderr
    try:
        latest = fetch_latest_version(current_version)
        _show_result(current_version, latest, error_stream)
        return True
    except (httpx.HTTPError, KeyError, TypeError, InvalidVersion, ValueError):
        click.echo(
            "Could not check PyPI. Continuing with the installed version.",
            file=error_stream,
        )
        return False


def prompt_for_update_check(
    current_version: str,
    release_date: str,
    *,
    stdin: TextIO | None = None,
    stderr: TextIO | None = None,
    state_path: Path | None = None,
    now: datetime | None = None,
) -> None:
    """Offer one disclosed PyPI check, then remain quiet for nine hours."""
    input_stream = stdin or sys.stdin
    error_stream = stderr or sys.stderr
    if not input_stream.isatty():
        return

    decision_time = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    path = state_path or get_update_state_path()
    state = _load_state(path)
    if state is not None and _state_is_fresh(state, decision_time):
        return

    try:
        released = date.fromisoformat(release_date)
        date_label = f"{released.strftime('%B')} {released.day}, {released.year}"
        release_summary = f"{date_label} - {release_age_text(release_date)}"
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
    consent = click.confirm("Check for update", default=False, err=True)
    if not consent:
        if not _record_decision(
            path,
            now=decision_time,
            consent=False,
            current_version=current_version,
            status="declined",
        ):
            click.echo(
                "Could not save this choice; Kulshan may ask again next run.",
                file=error_stream,
            )
        return

    latest: str | None = None
    status = "failed"
    try:
        latest = fetch_latest_version(current_version)
        _show_result(current_version, latest, error_stream)
        status = "checked"
    except (httpx.HTTPError, KeyError, TypeError, InvalidVersion, ValueError):
        click.echo(
            "Could not check PyPI. Continuing with the installed version.",
            file=error_stream,
        )
    if not _record_decision(
        path,
        now=decision_time,
        consent=True,
        current_version=current_version,
        latest_version=latest,
        status=status,
    ):
        click.echo(
            "Could not save this choice; Kulshan may ask again next run.",
            file=error_stream,
        )
