"""Fetch and fail-closed verify the pinned AWS CUDOS research sources.

The verifier reads Git objects only. It never executes upstream code, writes to
Kulshan production sources, or uploads local data.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import tempfile
from pathlib import Path
from typing import Any


class VerificationError(RuntimeError):
    """Raised when an upstream source does not match the manifest."""


def _git(repository: Path, *arguments: str) -> str:
    completed = subprocess.run(
        ["git", "-C", str(repository), *arguments],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    if completed.returncode:
        detail = completed.stderr.strip() or completed.stdout.strip()
        raise VerificationError(f"git {' '.join(arguments)} failed: {detail}")
    return completed.stdout.strip()


def load_manifest(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("schema_version") != "1.0":
        raise VerificationError("unsupported upstream manifest schema_version")
    sources = data.get("sources")
    if not isinstance(sources, list) or not sources:
        raise VerificationError("manifest must contain at least one source")
    return data


def verify_repository(source: dict[str, Any], repository: Path) -> None:
    expected_commit = source["pinned_commit"]
    actual_commit = _git(repository, "rev-parse", f"{expected_commit}^{{commit}}")
    if actual_commit != expected_commit:
        raise VerificationError(
            f"{source['source_id']}: commit mismatch: {actual_commit} != {expected_commit}"
        )
    remote_urls = {
        line.strip()
        for line in _git(repository, "remote", "get-url", "--all", "origin").splitlines()
    }
    if source["repository_url"] not in remote_urls:
        raise VerificationError(f"{source['source_id']}: repository URL mismatch")
    for selected in source["selected_files"]:
        path = selected["path"]
        expected_blob = selected["git_blob_sha1"]
        actual_blob = _git(repository, "rev-parse", f"{expected_commit}:{path}")
        if actual_blob != expected_blob:
            raise VerificationError(
                f"{source['source_id']}:{path}: blob mismatch: {actual_blob} != {expected_blob}"
            )
        _git(repository, "cat-file", "-e", f"{actual_blob}^{{blob}}")
    licence_path = source["licence_source_path"]
    if licence_path not in {item["path"] for item in source["selected_files"]}:
        raise VerificationError(f"{source['source_id']}: licence file is not hash-pinned")
    if source.get("verification_status") != "verified":
        raise VerificationError(f"{source['source_id']}: manifest status is not verified")


def _fetch_source(source: dict[str, Any], destination: Path) -> None:
    clone = subprocess.run(
        [
            "git",
            "clone",
            "--filter=blob:none",
            "--no-checkout",
            "--no-tags",
            source["repository_url"],
            str(destination),
        ],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    if clone.returncode:
        raise VerificationError(clone.stderr.strip() or "git clone failed")
    fetch = subprocess.run(
        [
            "git",
            "-C",
            str(destination),
            "fetch",
            "--depth",
            "1",
            "origin",
            source["pinned_commit"],
        ],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    if fetch.returncode:
        raise VerificationError(fetch.stderr.strip() or "git fetch failed")


def verify_manifest(
    manifest_path: Path, repository_overrides: dict[str, Path] | None = None
) -> None:
    manifest = load_manifest(manifest_path)
    overrides = repository_overrides or {}
    sources = manifest["sources"]
    if all(source["source_id"] in overrides for source in sources):
        for source in sources:
            verify_repository(source, overrides[source["source_id"]])
        return
    with tempfile.TemporaryDirectory(prefix="kulshan-cudos-verify-") as temp_dir:
        root = Path(temp_dir)
        for source in sources:
            source_id = source["source_id"]
            repository = overrides.get(source_id)
            if repository is None:
                repository = root / source_id
                _fetch_source(source, repository)
            verify_repository(source, repository)


def _parse_overrides(values: list[str]) -> dict[str, Path]:
    overrides: dict[str, Path] = {}
    for value in values:
        if "=" not in value:
            raise VerificationError("--source-root must use SOURCE_ID=PATH")
        source_id, path = value.split("=", 1)
        overrides[source_id] = Path(path).resolve()
    return overrides


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("manifest", type=Path)
    parser.add_argument(
        "--source-root",
        action="append",
        default=[],
        help="Use an existing checkout as SOURCE_ID=PATH instead of fetching it.",
    )
    args = parser.parse_args()
    verify_manifest(args.manifest.resolve(), _parse_overrides(args.source_root))
    print("Pinned AWS CUDOS sources verified.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
