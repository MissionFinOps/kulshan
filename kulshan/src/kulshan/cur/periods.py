"""Billing-period discovery and complete-month selection."""

from __future__ import annotations

import re
from datetime import date
from typing import Any

from kulshan.cur.manifest_reader import CurManifestError


def _list_objects(client, bucket: str, prefix: str) -> list[dict[str, Any]]:
    objects: list[dict[str, Any]] = []
    token: str | None = None
    while True:
        kwargs: dict[str, Any] = {"Bucket": bucket, "Prefix": prefix}
        if token:
            kwargs["ContinuationToken"] = token
        response = client.list_objects_v2(**kwargs)
        objects.extend(response.get("Contents", []))
        token = response.get("NextContinuationToken")
        if not response.get("IsTruncated") or not token:
            return objects


def list_manifest_periods(
    bucket: str,
    prefix: str,
    *,
    s3_client,
) -> list[str]:
    """Return billing months evidenced by manifests under an export prefix."""
    periods: set[str] = set()
    for obj in _list_objects(s3_client, bucket, prefix.strip("/") + "/"):
        key = str(obj.get("Key", ""))
        if not key.endswith("Manifest.json"):
            continue
        for pattern in (
            r"BILLING_PERIOD=(\d{4}-\d{2})",
            r"/(\d{4})(\d{2})\d{2}-\d{8}/",
            r"/(\d{4})-(\d{2})/",
        ):
            match = re.search(pattern, key)
            if not match:
                continue
            if len(match.groups()) == 1:
                periods.add(match.group(1))
            else:
                periods.add(f"{match.group(1)}-{match.group(2)}")
            break
    return sorted(periods)


def select_billing_period(
    periods: list[str],
    *,
    requested: str | None = None,
    today: date | None = None,
) -> tuple[str, bool]:
    """Select an explicit period or the newest complete calendar month."""
    valid = sorted(
        {
            period
            for period in periods
            if re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", period)
        }
    )
    current = (today or date.today()).strftime("%Y-%m")
    if requested:
        if not re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", requested):
            raise CurManifestError("Billing period must use YYYY-MM format.")
        if requested not in valid:
            raise CurManifestError(
                f"Billing period {requested} was not found in the export."
            )
        return requested, requested < current
    complete = [period for period in valid if period < current]
    if not complete:
        raise CurManifestError(
            "No complete CUR billing month is available. Specify "
            "--billing-period YYYY-MM to use an available partial month."
        )
    return complete[-1], True
