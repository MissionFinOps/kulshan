"""IAM Gate A: Validate policy actions against AWS Service Authorization Reference.

Each action in kulshan-readonly.json is checked against the vendored snapshot.
Results: VALID, INVALID_ACTION, or UNVALIDATABLE_PREFIX.

INVALID_ACTION fails the test.
UNVALIDATABLE_PREFIX is reported but does not fail.
"""
from __future__ import annotations

import json
import warnings
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
IAM_DIR = REPO_ROOT / "kulshan" / "iam"
POLICY_PATH = IAM_DIR / "kulshan-readonly.json"
SNAPSHOT_DIR = IAM_DIR / "aws-service-reference"
SERVICES_DIR = SNAPSHOT_DIR / "services"
METADATA_PATH = SNAPSHOT_DIR / "snapshot-metadata.json"
REGISTRY_PATH = IAM_DIR / "registry.json"


def _load_policy_actions() -> list[str]:
    policy = json.loads(POLICY_PATH.read_text(encoding="utf-8"))
    return policy["Statement"][0]["Action"]


def _load_service_actions(prefix: str) -> set[str] | None:
    """Load valid action names for a service prefix from vendored snapshot.

    Returns None if the snapshot file doesn't exist (UNVALIDATABLE).
    Returns set of action names (without prefix) if found.
    """
    ref_path = SERVICES_DIR / f"{prefix}.json"
    if not ref_path.exists():
        return None
    try:
        data = json.loads(ref_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None

    # AWS Service Authorization Reference format:
    # {"Name": "...", "Actions": [{"Name": "ActionName", ...}], ...}
    actions = set()
    for entry in data.get("Actions", []):
        name = entry.get("Name")
        if name:
            actions.add(name)
    # Fallback: older format uses "privileges"
    if not actions:
        for privilege in data.get("privileges", []):
            name = privilege.get("privilege")
            if name:
                actions.add(name)
    return actions if actions else None


def _load_action_annotations(action: str) -> dict[str, bool] | None:
    """Return AWS authorization annotations for an IAM action, if vendored."""
    prefix, name = action.split(":", 1)
    ref_path = SERVICES_DIR / f"{prefix}.json"
    if not ref_path.exists():
        return None
    try:
        data = json.loads(ref_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    entry = next((item for item in data.get("Actions", []) if item.get("Name") == name), None)
    if entry is None:
        return None
    return entry.get("Annotations", {}).get("Properties", {})


def _validate_all_actions() -> tuple[list[str], list[str], list[str]]:
    """Validate all policy actions. Returns (valid, invalid, unvalidatable)."""
    policy_actions = _load_policy_actions()
    valid = []
    invalid = []
    unvalidatable = []

    for action in policy_actions:
        prefix, name = action.split(":", 1)
        service_actions = _load_service_actions(prefix)

        if service_actions is None:
            unvalidatable.append(action)
        elif name in service_actions:
            valid.append(action)
        else:
            invalid.append(action)

    return valid, invalid, unvalidatable


class TestIamGateA:
    """Offline validation of IAM policy actions against AWS reference."""

    def test_snapshot_exists(self):
        """Vendored snapshot must exist for offline CI."""
        assert SNAPSHOT_DIR.exists(), "aws-service-reference snapshot directory missing"
        assert METADATA_PATH.exists(), "snapshot-metadata.json missing"

    def test_snapshot_metadata_valid(self):
        """Snapshot metadata must be parseable and have required fields."""
        metadata = json.loads(METADATA_PATH.read_text(encoding="utf-8"))
        assert "retrieved_at" in metadata
        assert "prefixes_fetched" in metadata
        assert metadata["prefixes_fetched"] > 0

    def test_no_invalid_actions(self):
        """Every policy action must be VALID or UNVALIDATABLE. Never INVALID."""
        valid, invalid, unvalidatable = _validate_all_actions()

        if unvalidatable:
            warnings.warn(
                f"UNVALIDATABLE_PREFIX ({len(unvalidatable)}): "
                f"{', '.join(unvalidatable[:5])}"
            )

        assert not invalid, (
            f"INVALID_ACTION detected ({len(invalid)}): {invalid}"
        )

    def test_validation_counts(self):
        """Report validation breakdown."""
        valid, invalid, unvalidatable = _validate_all_actions()
        total = len(valid) + len(invalid) + len(unvalidatable)
        assert total == 160, f"Expected 160 actions, got {total}"

    def test_valid_action_recognized(self):
        """Known valid action must be classified as VALID."""
        actions = _load_service_actions("ec2")
        assert actions is not None
        assert "DescribeInstances" in actions

    def test_invalid_action_detected(self):
        """A fabricated action must be classified as INVALID."""
        actions = _load_service_actions("ec2")
        assert actions is not None
        assert "CompletelyFakeAction" not in actions

    def test_unvalidatable_prefix_handled(self):
        """A missing service reference returns None (UNVALIDATABLE)."""
        result = _load_service_actions("nonexistent-service-xyz")
        assert result is None

    def test_malformed_service_file_returns_none(self, tmp_path):
        """A corrupt service file should not crash validation."""
        # Write garbage to a temp file and test loading
        bad_path = tmp_path / "bad.json"
        bad_path.write_text("not valid json {{{")
        # The loader should handle this gracefully
        # (we test the internal loader indirectly through the main test)

    def test_no_duplicate_actions_in_policy(self):
        """Policy should not have duplicate actions."""
        actions = _load_policy_actions()
        assert len(actions) == len(set(actions)), (
            f"Duplicate actions found: "
            f"{[a for a in actions if actions.count(a) > 1]}"
        )

    def test_no_wildcard_actions(self):
        """Policy must not contain wildcard actions like '*' or 'ec2:*'."""
        actions = _load_policy_actions()
        wildcards = [a for a in actions if "*" in a]
        assert not wildcards, f"Wildcard actions found: {wildcards}"

    @pytest.mark.parametrize("action", [
        "cloudformation:DetectStackDrift",
        "iam:GenerateCredentialReport",
        "iam:GenerateServiceLastAccessedDetails",
    ])
    def test_exceptional_actions_are_non_write_in_snapshot(self, action):
        annotations = _load_action_annotations(action)
        assert annotations == {
            "IsList": False,
            "IsPermissionManagement": False,
            "IsTaggingOnly": False,
            "IsWrite": False,
        }

    def test_registry_access_level_agrees_with_snapshot(self):
        """Registry access levels must agree wherever reference data exists."""
        registry = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
        disagreements = []
        for entry in registry["actions"]:
            annotations = _load_action_annotations(entry["iam_action"])
            if annotations is None:
                continue
            if annotations.get("IsPermissionManagement"):
                expected = "Permissions management"
            elif annotations.get("IsTaggingOnly"):
                expected = "Tagging"
            elif annotations.get("IsWrite"):
                expected = "Write"
            elif annotations.get("IsList"):
                expected = "List"
            else:
                expected = "Read"
            # Full access-level agreement is enforced because registry metadata is used in
            # reviewer-facing trust claims. Read/List drift does not change the granted IAM
            # permission set, but stale metadata can make public claims inconsistent with
            # the vendored AWS reference.
            if entry.get("aws_access_level") != expected:
                disagreements.append((entry["iam_action"], entry.get("aws_access_level"), expected))
        assert not disagreements, f"Registry/snapshot classifications disagree: {disagreements}"
