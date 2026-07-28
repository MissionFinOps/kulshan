"""Incremental cache refresh planning and transactional staging contracts."""

from __future__ import annotations

import json
import os
import tempfile
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any


class RefreshError(RuntimeError):
    """Refresh failed without replacing the previous valid state."""


@dataclass(frozen=True)
class RefreshPlan:
    state: str
    changed_files: tuple[str, ...]
    affected_partitions: tuple[str, ...]
    read_bytes: int
    reason: str


@dataclass(frozen=True)
class RefreshResult:
    state: str
    manifest_id: str | None
    replaced_partitions: tuple[str, ...]
    read_bytes: int
    freshness_updated: bool
    previous_preserved: bool


def plan_refresh(previous: Mapping[str, Any] | None, current: Mapping[str, Any]) -> RefreshPlan:
    if not current.get("manifest_id"):
        raise RefreshError("current manifest identity is required")
    if previous and previous.get("manifest_id") == current["manifest_id"]:
        return RefreshPlan("no-op", (), (), 0, "manifest identity is unchanged")
    old_files = {str(row["object_key"]): row for row in (previous or {}).get("files", ())}
    new_files = {str(row["object_key"]): row for row in current.get("files", ())}
    changed = tuple(sorted(key for key in new_files if old_files.get(key) != new_files[key]))
    removed = tuple(sorted(key for key in old_files if key not in new_files))
    changed = tuple(sorted(set(changed) | set(removed)))
    partitions = tuple(sorted({str(item) for item in current.get("periods", ())}))
    bytes_read = sum(
        int(new_files[key].get("size_bytes") or 0) for key in changed if key in new_files
    )
    return RefreshPlan(
        "refresh" if changed or not previous else "metadata-only",
        changed,
        partitions,
        bytes_read,
        "new or changed manifest identity",
    )


@contextmanager
def workspace_lock(workspace_path: Path) -> Iterator[None]:
    """Acquire an exclusive workspace lock and remove it on every exit."""
    lock_path = workspace_path / "reckoner.refresh.lock"
    workspace_path.mkdir(mode=0o700, parents=True, exist_ok=True)
    try:
        fd = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError as exc:
        raise RefreshError("another refresh is already running") from exc
    try:
        os.write(fd, str(os.getpid()).encode("ascii"))
        os.close(fd)
        yield
    finally:
        lock_path.unlink(missing_ok=True)


def transactional_refresh(
    workspace_path: Path,
    previous: Mapping[str, Any] | None,
    current: Mapping[str, Any],
    build_partitions: Any,
    *,
    validate: Any,
) -> RefreshResult:
    """Build staging state, validate it, then atomically replace metadata."""
    plan = plan_refresh(previous, current)
    if plan.state == "no-op":
        return RefreshResult(
            "no-op", previous.get("manifest_id") if previous else None, (), 0, False, True
        )
    state_path = workspace_path / "reckoner-cache-state.json"
    with workspace_lock(workspace_path):
        stage = Path(tempfile.mkdtemp(prefix="reckoner-stage-", dir=workspace_path))
        try:
            built = build_partitions(stage, plan)
            validate(built, current)
            payload = {
                "manifest_id": current["manifest_id"],
                "partitions": list(plan.affected_partitions),
                "fresh": True,
            }
            temp_state = state_path.with_suffix(".json.tmp")
            temp_state.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
            os.replace(temp_state, state_path)
            return RefreshResult(
                "refreshed",
                current["manifest_id"],
                plan.affected_partitions,
                plan.read_bytes,
                True,
                True,
            )
        except Exception as exc:
            raise RefreshError(f"staged refresh failed; previous cache preserved: {exc}") from exc
        finally:
            for child in stage.iterdir():
                if child.is_file():
                    child.unlink()
            stage.rmdir()
