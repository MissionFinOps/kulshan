"""IAM Gate B: Policy-registry bidirectional consistency.

Ensures:
A. required registry actions exist in composed policy
B. every composed-policy action exists in registry
C. per-check actions are registry-known
D. no duplicates or malformed declarations
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
IAM_DIR = REPO_ROOT / "kulshan" / "iam"
COMPOSED_PATH = IAM_DIR / "kulshan-readonly.json"
REGISTRY_PATH = IAM_DIR / "registry.json"
PER_CHECK_DIR = IAM_DIR / "per-check"


def _policy_actions() -> set[str]:
    policy = json.loads(COMPOSED_PATH.read_text(encoding="utf-8"))
    actions = policy["Statement"][0]["Action"]
    return set(actions)


def _registry_entries() -> list[dict]:
    registry = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
    return registry["actions"]


def _registry_actions() -> set[str]:
    return {e["iam_action"] for e in _registry_entries()}


def _per_check_actions() -> dict[str, set[str]]:
    """Map of per-check filename -> actions declared in that file."""
    result = {}
    for f in sorted(PER_CHECK_DIR.glob("*.json")):
        policy = json.loads(f.read_text(encoding="utf-8"))
        actions = set()
        for stmt in policy.get("Statement", []):
            a = stmt.get("Action", [])
            if isinstance(a, str):
                actions.add(a)
            else:
                actions.update(a)
        result[f.name] = actions
    return result


class TestGateBRequiredInPolicy:
    """A. Every registry-required baseline action is in the composed policy."""

    def test_required_actions_present(self):
        policy = _policy_actions()
        entries = _registry_entries()
        required = [
            e["iam_action"] for e in entries
            if e.get("status") == "required" and e.get("baseline_eligible")
        ]
        missing = [a for a in required if a not in policy]
        assert not missing, f"Required registry actions missing from policy: {missing}"


class TestGateBPolicyInRegistry:
    """B. Every composed-policy action has a registry entry."""

    def test_all_policy_actions_in_registry(self):
        policy = _policy_actions()
        registry = _registry_actions()
        not_in_registry = sorted(policy - registry)
        assert not not_in_registry, (
            f"Policy actions absent from registry ({len(not_in_registry)}): "
            f"{not_in_registry}"
        )


class TestGateBPerCheckConsistency:
    """C. Per-check fragments contain only registry-known actions."""

    @pytest.mark.parametrize("check_file", sorted(PER_CHECK_DIR.glob("*.json")))
    def test_per_check_actions_in_registry(self, check_file):
        registry = _registry_actions()
        policy = json.loads(check_file.read_text(encoding="utf-8"))
        actions = set()
        for stmt in policy.get("Statement", []):
            a = stmt.get("Action", [])
            if isinstance(a, str):
                actions.add(a)
            else:
                actions.update(a)
        unknown = actions - registry
        assert not unknown, (
            f"{check_file.name} has actions not in registry: {sorted(unknown)}"
        )


class TestGateBIntegrity:
    """D. No duplicates or structural issues."""

    def test_no_duplicate_policy_actions(self):
        policy = json.loads(COMPOSED_PATH.read_text(encoding="utf-8"))
        actions = policy["Statement"][0]["Action"]
        dupes = [a for a in actions if actions.count(a) > 1]
        assert not dupes, f"Duplicate actions in policy: {set(dupes)}"

    def test_no_duplicate_registry_entries(self):
        entries = _registry_entries()
        actions = [e["iam_action"] for e in entries]
        dupes = [a for a in actions if actions.count(a) > 1]
        assert not dupes, f"Duplicate registry entries: {set(dupes)}"

    def test_registry_entries_have_required_fields(self):
        entries = _registry_entries()
        for entry in entries:
            assert "iam_action" in entry, f"Entry missing iam_action: {entry}"
            assert "status" in entry, f"Entry missing status: {entry.get('iam_action')}"
            assert "capability" in entry, f"Entry missing capability: {entry.get('iam_action')}"

    def test_registry_status_values_valid(self):
        entries = _registry_entries()
        valid_statuses = {"required", "optional", "cross_account"}
        for entry in entries:
            assert entry["status"] in valid_statuses, (
                f"{entry['iam_action']} has invalid status: {entry['status']}"
            )


class TestGateBReconciliation:
    """Report reconciliation summary (informational, does not fail on unverified)."""

    def test_reconciliation_summary(self):
        """Print reconciliation counts for visibility."""
        policy = _policy_actions()
        registry = _registry_actions()
        entries = _registry_entries()

        in_both = policy & registry
        policy_only = policy - registry
        registry_only = registry - policy

        required_in_policy = sum(
            1 for e in entries
            if e.get("status") == "required" and e.get("baseline_eligible")
            and e["iam_action"] in policy
        )
        optional_in_registry = sum(
            1 for e in entries if e.get("status") == "optional"
        )

        # This test always passes; it's for visibility
        print(f"\n  IAM Gate B Reconciliation:")
        print(f"  Policy actions:         {len(policy)}")
        print(f"  Registry entries:       {len(registry)}")
        print(f"  In both:                {len(in_both)}")
        print(f"  Policy-only:            {len(policy_only)}")
        print(f"  Registry-only:          {len(registry_only)}")
        print(f"  Required+baseline:      {required_in_policy}")
        print(f"  Optional (registry):    {optional_in_registry}")
