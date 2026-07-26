"""CLI registration for CUR discovery, selection, and IAM generation."""

from __future__ import annotations

import json

import click
from rich.console import Console
from rich.table import Table

from kulshan.cur.discovery import (
    CurExportInfo,
    discover_cur_exports_detailed,
    rank_cur_exports,
)


def _resolved_session(ctx: click.Context):
    from kulshan.session import create_session, get_account_id

    root = ctx.find_root()
    session = create_session(
        profile=root.obj.get("profile"),
        role_arn=root.obj.get("role_arn"),
    )
    return session, get_account_id(session)


def _workspace(ctx: click.Context):
    from kulshan.workspace.resolution import resolve_workspace

    return resolve_workspace(ctx.find_root().obj.get("workspace"))


def _discover(ctx: click.Context):
    session, account_id = _resolved_session(ctx)
    workspace = _workspace(ctx)
    aws = workspace.config.aws if workspace and workspace.config.aws else None
    result = discover_cur_exports_detailed(
        session,
        session_account_id=account_id,
        payer_account_id=aws.payer_account_id if aws else None,
    )
    preferred = aws.cur_export if aws else None
    return (
        session,
        workspace,
        result,
        rank_cur_exports(result.exports, preferred_selector=preferred),
    )


def _find(exports: list[CurExportInfo], selector: str | None):
    if selector:
        normalized = selector.rstrip("/")
        for export in exports:
            if normalized in {
                export.export_arn,
                export.export_name,
                export.s3_uri.rstrip("/"),
            }:
                return export
        return None
    return exports[0] if exports else None


def register_cur_commands(cur_group) -> None:
    """Register commands on the existing ``kulshan cur`` group."""

    @cur_group.command("discover")
    @click.option("--json", "json_output", is_flag=True)
    @click.pass_context
    def discover_command(ctx: click.Context, json_output: bool) -> None:
        """List and rank modern Data Exports and legacy CUR definitions."""
        _session, _workspace_context, result, ranked = _discover(ctx)
        if json_output:
            click.echo(
                json.dumps(
                    {
                        "exports": [
                            {
                                "rank": index,
                                "name": export.export_name,
                                "provider": export.provider,
                                "s3_uri": export.s3_uri,
                                "format": export.format,
                                "status": export.status,
                                "authority_scope": export.authority_scope,
                                "selector": export.selector,
                            }
                            for index, export in enumerate(ranked, 1)
                        ],
                        "issues": [
                            {
                                "provider": issue.provider,
                                "operation": issue.operation,
                                "code": issue.code,
                            }
                            for issue in result.issues
                        ],
                    },
                    indent=2,
                )
            )
            return
        console = Console()
        table = Table(title="CUR/Data Export discovery")
        for column in (
            "Rank",
            "Name",
            "Provider",
            "Format",
            "Status",
            "Scope",
            "Destination",
        ):
            table.add_column(column)
        for index, export in enumerate(ranked, 1):
            table.add_row(
                str(index),
                export.export_name,
                export.provider,
                export.format,
                export.status,
                export.authority_scope,
                export.s3_uri,
            )
        console.print(table)
        for issue in result.issues:
            console.print(
                f"[yellow]Could not check {issue.provider} "
                f"{issue.operation}: {issue.code}[/yellow]"
            )

    @cur_group.command("select")
    @click.argument("selector")
    @click.option(
        "--cost-source",
        type=click.Choice(["auto", "ce", "hybrid", "cur"]),
        default="auto",
    )
    @click.pass_context
    def select_command(
        ctx: click.Context,
        selector: str,
        cost_source: str,
    ) -> None:
        """Persist a preferred export in the active bound workspace."""
        _session, workspace, _result, ranked = _discover(ctx)
        if not workspace.is_bound or not workspace.config.aws:
            raise click.ClickException(
                "CUR selection requires a bound workspace."
            )
        selected = _find(ranked, selector)
        if selected is None:
            raise click.ClickException(
                "Export not found. Run `kulshan cur discover` for selectors."
            )
        from kulshan.workspace.config import write_workspace_config

        workspace.config.aws.cur_export = selected.selector
        workspace.config.aws.cost_source = cost_source
        write_workspace_config(workspace.path, workspace.config)
        click.echo(
            f"Selected {selected.export_name} ({selected.provider}) "
            f"for workspace {workspace.name}."
        )

    @cur_group.command("iam")
    @click.option("--export", "selector", default=None)
    @click.option("--kms-key-arn", default=None)
    @click.pass_context
    def iam_command(
        ctx: click.Context,
        selector: str | None,
        kms_key_arn: str | None,
    ) -> None:
        """Generate, but never apply, scoped CUR read permissions."""
        session, _workspace_context, _result, ranked = _discover(ctx)
        selected = _find(ranked, selector)
        if selected is None:
            raise click.ClickException(
                "No matching export found. Run `kulshan cur discover`."
            )
        from kulshan.cur.iam import (
            detect_bucket_kms_key,
            generate_cur_access_policy,
        )

        key = kms_key_arn or detect_bucket_kms_key(session, selected)
        click.echo(
            json.dumps(
                generate_cur_access_policy(selected, kms_key_arn=key),
                indent=2,
            )
        )
        click.echo(
            "\nPolicy generated only; Kulshan did not modify IAM or S3.",
            err=True,
        )
