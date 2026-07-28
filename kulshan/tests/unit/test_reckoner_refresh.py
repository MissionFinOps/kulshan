from pathlib import Path

import pytest

from kulshan.reckoner.cache.refresh import (
    RefreshError,
    plan_refresh,
    transactional_refresh,
    workspace_lock,
)


def _manifest(manifest_id: str, size: int = 10) -> dict:
    return {
        "manifest_id": manifest_id,
        "periods": ["2026-01"],
        "files": [{"object_key": "a.parquet", "size_bytes": size}],
    }


def test_refresh_plan_noop_and_changed_bytes() -> None:
    assert plan_refresh(_manifest("same"), _manifest("same")).read_bytes == 0
    plan = plan_refresh(_manifest("old", 10), _manifest("new", 25))
    assert plan.changed_files == ("a.parquet",)
    assert plan.read_bytes == 25
    assert plan.affected_partitions == ("2026-01",)


def test_workspace_lock_rejects_concurrent_lock(tmp_path: Path) -> None:
    with workspace_lock(tmp_path), pytest.raises(RefreshError), workspace_lock(tmp_path):
        pass
    assert not (tmp_path / "reckoner.refresh.lock").exists()


def test_transactional_refresh_preserves_state_on_validation_failure(tmp_path: Path) -> None:
    previous = _manifest("old")
    state = tmp_path / "reckoner-cache-state.json"
    state.write_text('{"manifest_id":"old"}', encoding="utf-8")

    def build(stage, plan):
        (stage / "partition.tmp").write_text("staged", encoding="utf-8")
        return {"partitions": plan.affected_partitions}

    def validate(_built, _current):
        raise ValueError("payer mismatch")

    with pytest.raises(RefreshError, match="previous cache preserved"):
        transactional_refresh(tmp_path, previous, _manifest("new"), build, validate=validate)
    assert '"old"' in state.read_text(encoding="utf-8")
    assert not (tmp_path / "reckoner.refresh.lock").exists()


def test_transactional_refresh_replaces_only_after_validation(tmp_path: Path) -> None:
    def build(stage, plan):
        (stage / "partition.tmp").write_text("staged", encoding="utf-8")
        return {"partitions": plan.affected_partitions}

    result = transactional_refresh(
        tmp_path, None, _manifest("new"), build, validate=lambda *_: None
    )
    assert result.state == "refreshed"
    assert result.freshness_updated is True
    assert '"new"' in (tmp_path / "reckoner-cache-state.json").read_text(encoding="utf-8")
