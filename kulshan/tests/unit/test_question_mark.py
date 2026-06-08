"""Tests for the Kulshan.question_mark module."""
from __future__ import annotations

import click

from kulshan.question_mark import get_completions, render_help_overlay, resolve_context


class TestResolveContext:
    """Verify Click command tree walking."""

    def test_empty_tokens_returns_group_itself(self, simple_click_group):
        command, incomplete = resolve_context(simple_click_group, [])
        assert command is simple_click_group
        assert incomplete == ""

    def test_valid_subcommand_descends(self, simple_click_group):
        command, incomplete = resolve_context(simple_click_group, ["scan"])
        assert command.name == "scan"
        assert incomplete == ""

    def test_partial_name_returns_group_and_prefix(self, simple_click_group):
        command, incomplete = resolve_context(simple_click_group, ["sc"])
        assert command is simple_click_group
        assert incomplete == "sc"

    def test_nested_group_descends_two_levels(self, nested_click_group):
        command, incomplete = resolve_context(nested_click_group, ["sweep", "scan"])
        assert command.name == "scan"
        assert incomplete == ""

    def test_nested_group_partial_second_level(self, nested_click_group):
        command, incomplete = resolve_context(nested_click_group, ["cost", "an"])
        assert command.name == "cost"
        assert incomplete == "an"

    def test_unknown_token_returns_group_and_token(self, simple_click_group):
        command, incomplete = resolve_context(simple_click_group, ["nonexistent"])
        assert command is simple_click_group
        assert incomplete == "nonexistent"


class TestGetCompletions:
    """Verify completion candidate generation."""

    def test_group_lists_subcommands(self, simple_click_group):
        completions = get_completions(simple_click_group, "")
        names = [c["name"] for c in completions]
        assert "scan" in names
        assert "report" in names
        assert "fix" in names

    def test_command_lists_options(self, simple_click_group):
        scan_cmd = simple_click_group.commands["scan"]
        completions = get_completions(scan_cmd, "")
        names = [c["name"] for c in completions]
        assert "--profile" in names
        assert "--output" in names

    def test_prefix_filters_correctly(self, simple_click_group):
        completions = get_completions(simple_click_group, "re")
        names = [c["name"] for c in completions]
        assert "report" in names
        assert "scan" not in names
        assert "fix" not in names

    def test_no_match_returns_empty(self, simple_click_group):
        completions = get_completions(simple_click_group, "zzz")
        assert completions == []

    def test_completions_have_required_keys(self, simple_click_group):
        completions = get_completions(simple_click_group, "")
        for entry in completions:
            assert "name" in entry
            assert "help" in entry
            assert "type" in entry

    def test_completions_sorted_by_name(self, simple_click_group):
        completions = get_completions(simple_click_group, "")
        names = [c["name"] for c in completions]
        assert names == sorted(names)

    def test_option_prefix_filters(self, simple_click_group):
        scan_cmd = simple_click_group.commands["scan"]
        completions = get_completions(scan_cmd, "--p")
        names = [c["name"] for c in completions]
        assert "--profile" in names
        assert "--output" not in names


class TestRenderHelpOverlay:
    """Verify render_help_overlay does not crash."""

    def test_empty_completions_does_not_crash(self):
        render_help_overlay(
            completions=[],
            tool_name="Kulshan",
            theme="Kulshan",
            context_label="Kulshan",
        )

    def test_populated_completions_does_not_crash(self):
        completions = [
            {"name": "scan", "help": "Scan resources", "type": "command"},
            {"name": "--profile", "help": "AWS profile", "type": "option"},
        ]
        render_help_overlay(
            completions=completions,
            tool_name="Kulshan",
            theme="Kulshan",
            context_label="Kulshan scan",
        )

    def test_unknown_theme_does_not_crash(self):
        completions = [
            {"name": "report", "help": "Generate report", "type": "command"},
        ]
        render_help_overlay(
            completions=completions,
            tool_name="Kulshan",
            theme="nonexistent-theme",
            context_label="Kulshan",
        )
