#!/usr/bin/env python3
"""Fetch AWS Service Authorization Reference for Kulshan's IAM prefixes.

Downloads machine-readable action catalogs for each service prefix used in
kulshan-readonly.json. Stores them as a vendored snapshot for offline CI.

Usage:
    python iam/refresh_service_reference.py

Output:
    iam/aws-service-reference/snapshot-metadata.json
    iam/aws-service-reference/services/<prefix>.json
"""
from __future__ import annotations

import hashlib
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

try:
    import httpx
except ImportError:
    print("ERROR: httpx is required. Install with: pip install httpx")
    sys.exit(1)

IAM_DIR = Path(__file__).resolve().parent
POLICY_PATH = IAM_DIR / "kulshan-readonly.json"
SNAPSHOT_DIR = IAM_DIR / "aws-service-reference"
SERVICES_DIR = SNAPSHOT_DIR / "services"
METADATA_PATH = SNAPSHOT_DIR / "snapshot-metadata.json"

BASE_URL = "https://servicereference.us-east-1.amazonaws.com/v1"


def get_policy_prefixes() -> list[str]:
    """Extract service prefixes from the composed policy."""
    policy = json.loads(POLICY_PATH.read_text(encoding="utf-8"))
    actions = policy["Statement"][0]["Action"]
    return sorted(set(a.split(":")[0] for a in actions))


def fetch_service_reference(prefix: str, client: httpx.Client) -> dict | None:
    """Fetch a single service's action reference."""
    url = f"{BASE_URL}/{prefix}/{prefix}.json"
    try:
        resp = client.get(url, timeout=15)
        if resp.status_code == 200:
            return resp.json()
        print(f"  WARN: {prefix} returned HTTP {resp.status_code}")
        return None
    except Exception as e:
        print(f"  WARN: {prefix} fetch failed: {e}")
        return None


def main():
    prefixes = get_policy_prefixes()
    print(f"Fetching service reference for {len(prefixes)} prefixes...")

    SERVICES_DIR.mkdir(parents=True, exist_ok=True)

    client = httpx.Client()
    fetched = 0
    failed = []

    for prefix in prefixes:
        data = fetch_service_reference(prefix, client)
        if data:
            out_path = SERVICES_DIR / f"{prefix}.json"
            out_path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
            fetched += 1
            print(f"  OK: {prefix}")
        else:
            failed.append(prefix)
        time.sleep(0.2)  # Be polite

    client.close()

    # Write metadata
    metadata = {
        "retrieved_at": datetime.now(timezone.utc).isoformat(),
        "source_base_url": BASE_URL,
        "prefixes_requested": len(prefixes),
        "prefixes_fetched": fetched,
        "prefixes_failed": failed,
        "prefixes": prefixes,
    }
    METADATA_PATH.write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")

    print(f"\nDone: {fetched}/{len(prefixes)} fetched, {len(failed)} failed")
    if failed:
        print(f"Failed prefixes: {', '.join(failed)}")
    print(f"Snapshot written to: {SNAPSHOT_DIR}")


if __name__ == "__main__":
    main()
