"""Regression checks for user-facing source text."""

from pathlib import Path


def test_user_facing_source_contains_no_mojibake() -> None:
    """Prevent accidentally shipping text that was repeatedly mis-decoded."""
    package_root = Path(__file__).resolve().parents[2] / "src" / "kulshan"
    mojibake_markers = ("Ã", "Â", "â‚", "â€", "ðŸ", "ƒ", "Æ")

    offenders = []
    for path in package_root.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        if any(marker in text for marker in mojibake_markers):
            offenders.append(path.relative_to(package_root).as_posix())

    assert offenders == []
