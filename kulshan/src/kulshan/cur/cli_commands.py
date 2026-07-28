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
    import os

    from kulshan.workspace.onboarding import auto_onboard
    from kulshan.workspace.resolution import resolve_workspace, resolve_workspace_with_profile

    root = ctx.find_root()
    workspace_name = root.obj.get("workspace")
    profile = root.obj.get("profile") or os.environ.get("AWS_PROFILE")
    role_arn = root.obj.get("role_arn")
    if workspace_name:
        return resolve_workspace(workspace_name)
    workspace = resolve_workspace_with_profile(profile=profile, role_arn=role_arn)
    if workspace is not None:
        return workspace
    return auto_onboard(profile=profile, role_arn=role_arn).workspace_context


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
                f"[yellow]Could not check {issue.provider} {issue.operation}: {issue.code}[/yellow]"
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
            raise click.ClickException("CUR selection requires a bound workspace.")
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
            f"Selected {selected.export_name} ({selected.provider}) for workspace {workspace.name}."
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
            raise click.ClickException("No matching export found. Run `kulshan cur discover`.")
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

    @cur_group.group("catalog")
    def catalog_group() -> None:
        """Inspect the workspace-local CUR metadata catalogue."""

    @catalog_group.command("status")
    @click.option("--json", "json_output", is_flag=True)
    @click.pass_context
    def catalog_status_command(ctx: click.Context, json_output: bool) -> None:
        """Show coverage, manifest, and independent catalogue states."""
        from kulshan.cur.catalog import status

        workspace = _workspace(ctx)
        value = status(workspace.path)
        payload = value.__dict__
        if json_output:
            click.echo(json.dumps(payload, indent=2))
            return
        for key, item in payload.items():
            click.echo(f"{key}: {item}")

    @catalog_group.command("manifests")
    @click.pass_context
    def catalog_manifests_command(ctx: click.Context) -> None:
        """List immutable manifest versions recorded for the workspace."""
        from kulshan.cur.catalog import list_manifests

        workspace = _workspace(ctx)
        for manifest in list_manifests(workspace.path):
            click.echo(json.dumps(manifest.__dict__, sort_keys=True))

    @catalog_group.command("doctor")
    @click.pass_context
    def catalog_doctor_command(ctx: click.Context) -> None:
        """Report metadata consistency issues without scanning billing data."""
        from kulshan.cur.catalog import doctor

        workspace = _workspace(ctx)
        findings = doctor(workspace.path)
        if findings:
            for finding in findings:
                click.echo(finding, err=True)
            raise click.ClickException("catalogue requires attention")
        click.echo("CUR catalogue is consistent.")

    @catalog_group.command("refresh")
    @click.pass_context
    def catalog_refresh_command(ctx: click.Context) -> None:
        """Record discovered CUR/Data Export metadata without downloading objects."""
        from kulshan.cur.catalog import record_discovered_exports

        _session, workspace, _result, ranked = _discover(ctx)
        count = record_discovered_exports(workspace.path, ranked)
        click.echo(f"Recorded {count} export(s) in {workspace.path / 'cur-catalog.db'}.")

    @catalog_group.command("estimate")
    @click.pass_context
    def catalog_estimate_command(ctx: click.Context) -> None:
        """Show known storage and whether an S3 estimate is still required."""
        from kulshan.cur.catalog import storage_estimate

        workspace = _workspace(ctx)
        click.echo(json.dumps(storage_estimate(workspace.path).__dict__, indent=2))
