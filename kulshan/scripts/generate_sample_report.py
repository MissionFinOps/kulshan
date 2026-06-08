"""Generate the sanitized sample Kulshan Report.

Regenerates ``samples/sample-report.html`` and ``samples/sample-report.json``
from the committed fixture data at ``Kulshan/tests/fixtures/checks/*.json``.

Output is deterministic: timestamp, account id, regions, and duration are
frozen constants so re-running this script twice produces byte-identical
files. A pytest drift guard at ``Kulshan/tests/unit/test_sample_report.py``
fails CI if the committed artifacts do not match what regeneration would
produce against the current fixtures and renderer.

Run from anywhere::

    python Kulshan/scripts/generate_sample_report.py

No AWS access. No network. No environment variables. No arguments.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from kulshan.__version__ import __version__
from kulshan.findings_ranker import flatten_findings, top_n
from kulshan.orchestrator import TOOL_ORDER, compute_overall
from kulshan.report.html import generate_html_report

# ── frozen, sanitized inputs ─────────────────────────────────────────────────
# Changes here will require regenerating the committed sample artifacts.

SAMPLE_TIMESTAMP = datetime(2026, 4, 30, 12, 0, 0, tzinfo=timezone.utc)
SAMPLE_ACCOUNT_ID = "000000000000"
SAMPLE_REGIONS = ["us-east-1", "us-west-2", "eu-west-1"]
SAMPLE_DURATION_SECS = 12.4

# ── paths (resolved from this script's location) ─────────────────────────────

SCRIPT_DIR = Path(__file__).resolve().parent      # Kulshan/scripts/
WHEEL_DIR = SCRIPT_DIR.parent                     # Kulshan/
REPO_ROOT = WHEEL_DIR.parent                      # mission-finops/

FIXTURES_DIR = WHEEL_DIR / "tests" / "fixtures" / "checks"
SAMPLES_DIR = REPO_ROOT / "samples"
HTML_OUT = SAMPLES_DIR / "sample-report.html"
JSON_OUT = SAMPLES_DIR / "sample-report.json"


def load_fixtures() -> dict:
    """Load every pack fixture into a results dict keyed by tool name."""
    results: dict = {}
    for tool_key in TOOL_ORDER:
        path = FIXTURES_DIR / f"{tool_key}.json"
        with path.open(encoding="utf-8") as f:
            results[tool_key] = json.load(f)
    return results


def compute_inputs(results: dict) -> tuple:
    """Return ``(overall_score, overall_grade, all_findings, top_actions)``."""
    overall_score, overall_grade = compute_overall(results)
    all_findings = flatten_findings(results)
    top_actions = top_n(all_findings, n=10)
    return overall_score, overall_grade, all_findings, top_actions


def build_html(
    results: dict,
    top_actions: list,
    overall_score: int,
    overall_grade: str,
) -> str:
    """Render the HTML report with a frozen timestamp."""
    # Patch the imported ``datetime`` reference inside report.html so the
    # report's ``Generated`` line is reproducible. No product code changes.
    with patch("kulshan.report.html.datetime") as mock_dt:
        mock_dt.now.return_value = SAMPLE_TIMESTAMP
        return generate_html_report(
            results=results,
            overall_score=overall_score,
            overall_grade=overall_grade,
            account_id=SAMPLE_ACCOUNT_ID,
            regions=SAMPLE_REGIONS,
            duration_secs=SAMPLE_DURATION_SECS,
            top_actions=top_actions,
            synthetic_sample=True,
        )


def build_json(
    results: dict,
    top_actions: list,
    overall_score: int,
    overall_grade: str,
    all_findings: list,
) -> str:
    """Build the same JSON payload ``Kulshan Report --format json`` produces."""
    payload = {
        "kulshan_version": __version__,
        "account_id": SAMPLE_ACCOUNT_ID,
        "regions": SAMPLE_REGIONS,
        "duration_seconds": SAMPLE_DURATION_SECS,
        "overall_score": overall_score,
        "overall_grade": overall_grade,
        "tools": results,
        "findings": all_findings,
        "top_actions": top_actions,
    }
    return json.dumps(payload, indent=2, default=str)


def main() -> int:
    results = load_fixtures()
    overall_score, overall_grade, all_findings, top_actions = compute_inputs(results)

    html_str = build_html(results, top_actions, overall_score, overall_grade)
    json_str = build_json(
        results, top_actions, overall_score, overall_grade, all_findings
    )

    SAMPLES_DIR.mkdir(parents=True, exist_ok=True)
    # write_bytes avoids any platform newline translation; the drift-guard
    # test reads with universal newlines so cross-platform compare still works.
    HTML_OUT.write_bytes(html_str.encode("utf-8"))
    JSON_OUT.write_bytes(json_str.encode("utf-8"))

    print(f"Wrote {HTML_OUT}")
    print(f"Wrote {JSON_OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
