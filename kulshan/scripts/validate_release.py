"""Validate that a release tag matches package and changelog metadata."""

from __future__ import annotations

import argparse
import re
import sys
from datetime import date
from pathlib import Path

SEMVER_TAG = re.compile(
    r"^v(?P<version>(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)\.(?:0|[1-9]\d*))$"
)
VERSION_ASSIGNMENT = re.compile(r'^__version__\s*=\s*["\'](?P<value>[^"\']+)["\']$', re.MULTILINE)
DATE_ASSIGNMENT = re.compile(
    r'^__release_date__\s*=\s*["\'](?P<value>[^"\']+)["\']$', re.MULTILINE
)


def validate(tag: str, project_root: Path) -> list[str]:
    """Return release metadata errors for *tag*."""
    errors: list[str] = []
    tag_match = SEMVER_TAG.fullmatch(tag)
    if tag_match is None:
        return [f"release tag must use exact vMAJOR.MINOR.PATCH form; got {tag!r}"]

    expected_version = tag_match.group("version")
    version_path = project_root / "src" / "kulshan" / "__version__.py"
    changelog_path = project_root / "CHANGELOG.md"
    version_text = version_path.read_text(encoding="utf-8")

    version_match = VERSION_ASSIGNMENT.search(version_text)
    if version_match is None:
        errors.append(f"could not read __version__ from {version_path}")
    elif version_match.group("value") != expected_version:
        errors.append(
            f"tag {tag!r} does not match package version {version_match.group('value')!r}"
        )

    date_match = DATE_ASSIGNMENT.search(version_text)
    if date_match is None:
        errors.append(f"could not read __release_date__ from {version_path}")
    else:
        try:
            release_date = date.fromisoformat(date_match.group("value"))
        except ValueError:
            errors.append("__release_date__ must use YYYY-MM-DD format")
        else:
            if release_date > date.today():
                errors.append("__release_date__ cannot be in the future")

    changelog = changelog_path.read_text(encoding="utf-8")
    heading = re.compile(
        rf"^## \[{re.escape(expected_version)}\] - \d{{4}}-\d{{2}}-\d{{2}}$", re.MULTILINE
    )
    if heading.search(changelog) is None:
        errors.append(f"CHANGELOG.md has no dated [{expected_version}] release heading")

    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tag", required=True, help="Git tag being published")
    parser.add_argument(
        "--project-root",
        type=Path,
        default=Path(__file__).resolve().parents[1],
        help="Directory containing pyproject.toml and CHANGELOG.md",
    )
    args = parser.parse_args()

    errors = validate(args.tag, args.project_root.resolve())
    if errors:
        for error in errors:
            print(f"release validation failed: {error}", file=sys.stderr)
        return 1

    print(f"release metadata validated for {args.tag}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
