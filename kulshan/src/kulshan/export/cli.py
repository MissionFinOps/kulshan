"""CLI commands for consultant evidence export and alias resolution."""
from __future__ import annotations

import os
import shutil
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import click
from rich.console import Console

from kulshan.constants import ExitCode


@click.group()
def export():
    """Export evidence packages for external sharing."""
    pass


@export.command("consultant")
@click.argument("cur_path", type=click.Path(exists=True), required=False, default=None)
@click.option("--s3", "s3_uri", default=None,
              help="S3 URI of CUR/Data Export (e.g. s3://bucket/prefix).")
@click.option("-w", "--workspace", "workspace_name", default=None,
              help="Workspace name (resolves S3 source from workspace cur_export config).")
@click.option("-c", "--connection", "connection_name", default=None,
              help="Named AWS connection within the workspace.")
@click.option("--from", "from_date", required=True, type=click.DateTime(formats=["%Y-%m-%d"]),
              help="Start date (inclusive) YYYY-MM-DD.")
@click.option("--to", "to_date", required=True, type=click.DateTime(formats=["%Y-%m-%d"]),
              help="End date (exclusive) YYYY-MM-DD.")
@click.option("--account", "accounts", multiple=True, help="Include only these account IDs.")
@click.option("--exclude-account", "exclude_accounts", multiple=True)
@click.option("--service", "services", multiple=True, help="Include only these services.")
@click.option("--exclude-service", "exclude_services", multiple=True)
@click.option("--keep-tag", "keep_tags", multiple=True, help="Tag keys to preserve (values still scanned).")
@click.option("--drop-unclassified-columns", is_flag=True, default=False,
              help="Drop unclassified columns instead of blocking export.")
@click.option("--ce/--no-ce", "include_ce", default=False,
              help="Include Cost Explorer evidence (requires AWS credentials).")
@click.option("--profile", default=None, help="AWS profile for CE access.")
@click.option("-o", "--output", type=click.Path(), default=None, help="Output ZIP path.")
def consultant(
    cur_path: str | None,
    s3_uri: str | None,
    workspace_name: str | None,
    connection_name: str | None,
    from_date: datetime,
    to_date: datetime,
    accounts: tuple[str, ...],
    exclude_accounts: tuple[str, ...],
    services: tuple[str, ...],
    exclude_services: tuple[str, ...],
    keep_tags: tuple[str, ...],
    drop_unclassified_columns: bool,
    include_ce: bool,
    profile: str | None,
    output: str | None,
) -> None:
    """Create a pseudonymized consultant evidence package from CUR data.

    Provide EXACTLY ONE source: a local CUR_PATH or --s3 / --workspace for S3.

    \\b
    Examples:
      # Local source
      kulshan export consultant ./cur-data \\
        --from 2026-07-01 --to 2026-08-01 \\
        --keep-tag environment \\
        -o consultant-export.zip

      # S3 source via workspace
      kulshan export consultant -w my-workspace \\
        --from 2026-07-01 --to 2026-08-01 \\
        -o consultant-export.zip

      # S3 source via explicit URI
      kulshan export consultant --s3 s3://my-bucket/cur-prefix \\
        --from 2026-07-01 --to 2026-08-01 \\
        -o consultant-export.zip
    """
    from kulshan.export.cur_export import ExportBlockedError, export_cur
    from kulshan.export.gates import gate_integrity, gate_residual, gate_schema
    from kulshan.export.package import stage_package, write_zip
    from kulshan.export.scope import EvidenceScope
    from kulshan.pseudonym.context import resolve_workspace_secret_path
    from kulshan.pseudonym.engine import PseudonymizationEngine
    from kulshan.pseudonym.policy import PseudonymPolicy
    from kulshan.pseudonym.secret import SECRET_FILENAME

    console = Console(stderr=True)

    # ── Source selection: exactly one of local or S3 ─────────────────────
    s3_manifest = None
    s3_session = None
    selected_workspace_path = None

    # Determine if S3 source is requested via --s3 or --workspace
    has_s3_source = bool(s3_uri or workspace_name)

    if cur_path and has_s3_source:
        console.print(
            "[red]ERROR[/red]: Cannot specify both a local CUR_PATH"
            " and --s3/--workspace."
        )
        console.print("Provide exactly one source: a local path OR an S3 source.")
        sys.exit(ExitCode.CONFIG_ERROR)

    if not cur_path and not has_s3_source:
        console.print("[red]ERROR[/red]: No source specified.")
        console.print("Provide a local CUR_PATH argument or use --s3 / --workspace for S3 source.")
        sys.exit(ExitCode.CONFIG_ERROR)

    if include_ce and (services or exclude_services):
        service_filter = (services or exclude_services)[0]
        console.print(
            f"[red]ERROR[/red]: Service filter '{service_filter}' cannot be resolved "
            "unambiguously for both CUR and Cost Explorer."
        )
        console.print("Remove the service filter or run separate CUR and CE exports.")
        sys.exit(ExitCode.CONFIG_ERROR)

    if has_s3_source:
        import boto3

        from kulshan.cur.manifest_reader import read_manifest_uri

        if s3_uri:
            # Direct S3 URI
            session_kwargs: dict = {}
            if profile:
                session_kwargs["profile_name"] = profile
            s3_session = boto3.Session(**session_kwargs)
            s3_manifest = read_manifest_uri(
                s3_uri, session=s3_session
            )
        else:
            # Workspace-based: read cur_export from workspace config
            from kulshan.workspace.resolution import resolve_workspace
            ws_ctx = resolve_workspace(workspace_name)
            selected_workspace_path = ws_ctx.path
            if ws_ctx.config.aws is None or not ws_ctx.config.aws.cur_export:
                console.print(
                    f"[red]ERROR[/red]: Workspace '{workspace_name}' has no cur_export configured."
                )
                console.print("Set aws.cur_export in workspace.toml or use --s3 directly.")
                sys.exit(ExitCode.RUNTIME_ERROR)
            conn = ws_ctx.config.aws.get_connection(
                connection_name or ws_ctx.config.aws.default_connection
            )
            if include_ce and conn is not None:
                role_arn = getattr(conn, "role_arn", None)
                if role_arn:
                    console.print(
                        "[red]ERROR[/red]: Cost Explorer cannot use the workspace role ARN "
                        "in consultant export."
                    )
                    console.print(
                        "Pass --profile for a direct profile connection without a role ARN."
                    )
                    sys.exit(ExitCode.CONFIG_ERROR)
                connection_profile = getattr(conn, "profile", None)
                if profile is None and connection_profile is not None:
                    console.print(
                        "[red]ERROR[/red]: Cost Explorer would use ambient credentials while "
                        f"CUR uses workspace profile '{connection_profile}'."
                    )
                    console.print(
                        f"Pass --profile {connection_profile} so both datasets use "
                        "the same credentials."
                    )
                    sys.exit(ExitCode.CONFIG_ERROR)
            effective_profile = profile or (conn.profile if conn else None)
            session_kwargs = {}
            if effective_profile:
                session_kwargs["profile_name"] = effective_profile
            s3_session = boto3.Session(**session_kwargs)
            s3_manifest = read_manifest_uri(
                ws_ctx.config.aws.cur_export, session=s3_session
            )

    # Build scope
    scope = EvidenceScope(
        from_date=from_date.date(),
        to_date=to_date.date(),
        include_accounts=tuple(accounts),
        exclude_accounts=tuple(exclude_accounts),
        include_services=tuple(services),
        exclude_services=tuple(exclude_services),
    )

    # Create engine with consultant-strict policy (no bypass)
    ws_path = selected_workspace_path or resolve_workspace_secret_path()
    policy = PseudonymPolicy(mode="consultant", tty_bypass=False, show_identifiers=False)
    engine = PseudonymizationEngine.create(ws_path, policy)

    if output is None:
        ws_name = ws_path.name if ws_path else "default"
        ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        output = f"consultant-export-{ws_name}-{ts}.zip"
    output_path = Path(output).resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)

    source_label = cur_path if cur_path else (s3_uri or f"workspace:{workspace_name}")
    console.print("[bold]Kulshan Consultant Evidence Export[/bold]")
    console.print(f"  Period: {scope.from_date} to {scope.to_date}")
    console.print(f"  Source: {source_label}")
    console.print()

    # Create temp working directory
    work_dir = Path(tempfile.mkdtemp(prefix=".kulshan-export-", dir=output_path.parent))
    cur_dir = work_dir / "cur"
    ce_dir = work_dir / "ce"

    try:
        # ── CUR Export ───────────────────────────────────────────────────
        console.print("[dim]Exporting CUR data...[/dim]")
        try:
            cur_result = export_cur(
                cur_path=cur_path or "",
                scope=scope,
                engine=engine,
                output_dir=cur_dir,
                keep_tags=frozenset(keep_tags),
                drop_unclassified=drop_unclassified_columns,
                s3_session=s3_session,
                s3_manifest=s3_manifest,
            )
        except ExportBlockedError as e:
            console.print(f"[red]EXPORT BLOCKED[/red]: {e}")
            console.print("[dim]Use --drop-unclassified-columns to drop them, or add --keep-tag.[/dim]")
            sys.exit(ExitCode.RUNTIME_ERROR)

        console.print(f"  Rows: {cur_result.row_count:,}")
        console.print(f"  Columns: {cur_result.column_count}")
        if cur_result.dropped_columns:
            console.print(f"  Dropped: {len(cur_result.dropped_columns)} columns")

        if cur_result.row_count > 20_000_000:
            console.print(f"  [yellow]Warning: {cur_result.row_count:,} rows is large.[/yellow]")

        # ── CE Export (optional) ─────────────────────────────────────────
        ce_result = None
        if include_ce:
            console.print()
            console.print("[dim]Exporting Cost Explorer evidence...[/dim]")
            import boto3

            from kulshan.export.ce_export import CeTruncationError, export_ce

            session_kwargs = {}
            if profile:
                session_kwargs["profile_name"] = profile
            session = s3_session if s3_session is not None else boto3.Session(**session_kwargs)

            try:
                ce_result = export_ce(session, scope, engine, ce_dir)
                console.print(f"  Datasets: {len(ce_result.datasets)}")
                console.print(f"  Rows: {ce_result.total_rows:,}")
            except CeTruncationError as e:
                console.print(f"[red]CE EXPORT FAILED[/red]: {e}")
                sys.exit(ExitCode.RUNTIME_ERROR)

        # ── Gate 1: Schema ───────────────────────────────────────────────
        console.print()
        package_dir = work_dir / "package"
        projected_gates = [
            {"gate": "schema", "passed": True},
            {"gate": "integrity", "passed": True},
            {"gate": "residual", "passed": True},
        ]
        stage_package(
            package_dir,
            cur_dir,
            ce_dir if ce_result else None,
            scope,
            cur_result.classification,
            projected_gates,
            cur_result.row_count,
            ce_result.datasets if ce_result else None,
            cur_result.dropped_columns,
            list(keep_tags),
            engine,
        )

        g1 = gate_schema(cur_result.classification, drop_unclassified_columns)
        if not g1.passed:
            console.print("[red]GATE 1 FAILED: Schema classification[/red]")
            for f in g1.failures:
                console.print(f"  {f}")
            sys.exit(ExitCode.RUNTIME_ERROR)
        console.print("[green]Gate 1 PASS[/green]: Schema classification")

        # ── Gate 2: Integrity ────────────────────────────────────────────
        # Identify numeric SAFE columns for per-row verification
        from kulshan.export.columns import ColumnClass as _CC
        numeric_safe = [
            c for c, cls in cur_result.classification.items()
            if cls == _CC.SAFE and any(
                c.startswith(p) for p in (
                    "line_item_unblended", "line_item_blended", "line_item_net",
                    "line_item_normalized_usage_amount", "line_item_usage_amount",
                    "pricing_", "discount_", "savings_plan_net_",
                    "savings_plan_total_commitment", "savings_plan_used_commitment",
                    "reservation_amortized_", "reservation_effective_cost",
                    "reservation_net_", "reservation_unused_",
                )
            )
        ]
        # Pseudonymize columns for building distinguishing dimensions
        pseudo_cols = [
            c for c, cls in cur_result.classification.items()
            if cls == _CC.PSEUDONYMIZE
        ]
        # Safe non-numeric dimensions for distinguishing rows
        safe_dims = [
            c for c, cls in cur_result.classification.items()
            if cls == _CC.SAFE and c not in numeric_safe
        ]

        # Build source path for comparison (raw source, Gate 2 applies scope independently)
        if cur_path:
            from kulshan.cur.source import local_parquet_source
            source_parquet = local_parquet_source(cur_path)
        else:
            # S3 source: Gate 2 not feasible without local re-read;
            # rely on row count + export internal consistency
            source_parquet = None

        g2 = gate_integrity(
            cur_result.source_row_count,
            cur_result.row_count,
            source_path=source_parquet,
            output_path=(package_dir / "cur" / cur_result.output_path.name).as_posix(),
            numeric_columns=numeric_safe,
            pseudo_columns=pseudo_cols,
            safe_dimensions=safe_dims,
            engine=engine,
            scope=scope,
            s3_manifest=s3_manifest,
            s3_session=s3_session,
        )
        if not g2.passed:
            console.print("[red]GATE 2 FAILED: Evidence integrity[/red]")
            for f in g2.failures:
                console.print(f"  {f}")
            sys.exit(ExitCode.RUNTIME_ERROR)
        console.print("[green]Gate 2 PASS[/green]: Evidence integrity")

        manifest_count = _manifest_cur_row_count(package_dir / "manifest.json")
        if manifest_count != cur_result.row_count:
            console.print("[red]GATE 2 FAILED: Evidence integrity[/red]")
            console.print(
                f"  Manifest row count mismatch: manifest={manifest_count}, "
                f"output={cur_result.row_count}"
            )
            sys.exit(ExitCode.RUNTIME_ERROR)

        # ── Gate 3: Residual identifiers ─────────────────────────────────
        # Collect source identifiers from pseudonymize columns
        source_ids = _collect_source_identifiers(
            cur_path,
            scope,
            cur_result.classification,
            s3_manifest=s3_manifest,
            s3_session=s3_session,
        )
        # Collect all output text
        secret_path = ws_path / SECRET_FILENAME

        try:
            output_text = _iter_output_text(package_dir)
            g3 = gate_residual(source_ids, output_text, secret_path)
        except Exception as exc:
            console.print("[red]GATE 3 FAILED: Residual identifiers[/red]")
            console.print(f"  Output scan error: {type(exc).__name__}: {exc}")
            sys.exit(ExitCode.RUNTIME_ERROR)
        if not g3.passed:
            console.print("[red]GATE 3 FAILED: Residual identifiers[/red]")
            for f in g3.failures:
                console.print(f"  {f}")
            sys.exit(ExitCode.RUNTIME_ERROR)

        gate_dicts = [
            {"gate": gate.gate, "passed": gate.passed, "details": gate.details}
            for gate in (g1, g2, g3)
        ]
        _write_privacy_gate_results(package_dir / "privacy-report.json", gate_dicts)
        try:
            final_g3 = gate_residual(
                source_ids, _iter_output_text(package_dir), secret_path
            )
        except Exception as exc:
            console.print("[red]GATE 3 FAILED: Final package scan[/red]")
            console.print(f"  Output scan error: {type(exc).__name__}: {exc}")
            sys.exit(ExitCode.RUNTIME_ERROR)
        if not final_g3.passed:
            console.print("[red]GATE 3 FAILED: Final package scan[/red]")
            for failure in final_g3.failures:
                console.print(f"  {failure}")
            sys.exit(ExitCode.RUNTIME_ERROR)
        console.print("[green]Gate 3 PASS[/green]: Residual identifier scan")

        # ── Package ──────────────────────────────────────────────────────
        console.print()
        temporary_zip = work_dir / "consultant-export.zip"
        try:
            write_zip(temporary_zip, package_dir)
            os.replace(temporary_zip, output_path)
        except Exception as exc:
            console.print("[red]PACKAGE FAILED[/red]: Validated ZIP was not published")
            console.print(f"  {type(exc).__name__}: {exc}")
            sys.exit(ExitCode.RUNTIME_ERROR)
        zip_path = output_path

        console.print(f"[bold green]Evidence package created:[/bold green] {zip_path}")
        console.print(f"  CUR rows: {cur_result.row_count:,}")
        if ce_result:
            console.print(f"  CE datasets: {len(ce_result.datasets)}")

    finally:
        # Clean up temp directory
        shutil.rmtree(work_dir, ignore_errors=True)


def _collect_source_identifiers(
    cur_path: str | None,
    scope,
    classification: dict,
    s3_manifest=None,
    s3_session=None,
) -> set[str]:
    """Collect distinct identifier values from PSEUDONYMIZE columns in source."""
    from kulshan.cur.duckdb_engine import connect_memory, cur_raw_columns, register_cur_raw
    from kulshan.cur.source import local_parquet_source
    from kulshan.export.columns import ColumnClass

    if s3_manifest is not None:
        from kulshan.cur.s3_query import _source_sql, connect_s3_duckdb
        from kulshan.cur.schema import resolve_cur_columns

        con = connect_s3_duckdb(session=s3_session)
        con.execute(f"CREATE VIEW cur_raw AS SELECT * FROM {_source_sql(s3_manifest)}")
        columns = cur_raw_columns(con)
        mapping = resolve_cur_columns(columns)
    else:
        source = local_parquet_source(cur_path or "")
        con = connect_memory()
        mapping = register_cur_raw(con, source)
        columns = cur_raw_columns(con)
    try:
        where = scope.duckdb_where_clause(mapping.usage_start, mapping.account_id, mapping.service)

        identifiers: set[str] = set()
        pseudo_cols = [
            c for c, cls in classification.items()
            if cls == ColumnClass.PSEUDONYMIZE and c in columns
        ]

        for col in pseudo_cols:
            rows = con.execute(
                f'SELECT DISTINCT CAST("{col}" AS VARCHAR) FROM cur_raw '
                f"WHERE {where} AND \"{col}\" IS NOT NULL"
            ).fetchall()
            for row in rows:
                val = str(row[0]).strip()
                if val:
                    identifiers.add(val)

        return identifiers
    finally:
        con.close()


def _manifest_cur_row_count(manifest_path: Path) -> int:
    """Read the staged manifest row count, failing closed on invalid metadata."""
    import json

    return int(json.loads(manifest_path.read_text(encoding="utf-8"))["cur"]["row_count"])


def _write_privacy_gate_results(privacy_path: Path, gate_results: list[dict]) -> None:
    """Write real gate results before the final package scan."""
    import json

    report = json.loads(privacy_path.read_text(encoding="utf-8"))
    report["gates"] = gate_results
    privacy_path.write_text(json.dumps(report, indent=2), encoding="utf-8")


def _iter_output_text(package_dir: Path):
    """Yield (source_label, text) for every staged package member, so a Gate 3
    failure can name the file it fired on without printing the leaked value."""
    import duckdb

    for path in sorted(item for item in package_dir.rglob("*") if item.is_file()):
        label = path.relative_to(package_dir).as_posix()
        if path.suffix != ".parquet":
            yield label, path.read_text(encoding="utf-8")
            continue
        con = duckdb.connect(":memory:")
        try:
            escaped = path.as_posix().replace("'", "''")
            description = con.execute(
                f"DESCRIBE SELECT * FROM read_parquet('{escaped}')"
            ).fetchall()
            columns = ", ".join(
                f'CAST("{str(row[0]).replace(chr(34), chr(34) * 2)}" AS VARCHAR)'
                for row in description
            )
            cursor = con.execute(f"SELECT {columns} FROM read_parquet('{escaped}')")
            while True:
                rows = cursor.fetchmany(10_000)
                if not rows:
                    break
                yield label, " ".join(
                    str(value) for row in rows for value in row if value is not None
                )
        finally:
            con.close()
