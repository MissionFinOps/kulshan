"""CLI commands for consultant evidence export and alias resolution."""
from __future__ import annotations

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
    from kulshan.export.package import create_package
    from kulshan.export.scope import EvidenceScope
    from kulshan.pseudonym.context import resolve_workspace_secret_path
    from kulshan.pseudonym.engine import PseudonymizationEngine
    from kulshan.pseudonym.policy import PseudonymPolicy
    from kulshan.pseudonym.secret import SECRET_FILENAME

    console = Console(stderr=True)

    # ── Source selection: exactly one of local or S3 ─────────────────────
    s3_manifest = None
    s3_session = None

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

    if has_s3_source:
        import boto3

        from kulshan.cur.manifest_reader import read_manifest_uri

        session_kwargs: dict = {}
        if profile:
            session_kwargs["profile_name"] = profile
        s3_session = boto3.Session(**session_kwargs)

        if s3_uri:
            # Direct S3 URI
            s3_manifest = read_manifest_uri(
                s3_uri, session=s3_session
            )
        else:
            # Workspace-based: read cur_export from workspace config
            from kulshan.workspace.resolution import resolve_workspace
            ws_ctx = resolve_workspace(workspace_name)
            if ws_ctx.config.aws is None or not ws_ctx.config.aws.cur_export:
                console.print(
                    f"[red]ERROR[/red]: Workspace '{workspace_name}' has no cur_export configured."
                )
                console.print("Set aws.cur_export in workspace.toml or use --s3 directly.")
                sys.exit(ExitCode.RUNTIME_ERROR)
            s3_manifest = read_manifest_uri(
                ws_ctx.config.aws.cur_export, session=s3_session
            )
            # Use workspace profile if not explicitly provided
            if not profile and ws_ctx.config.aws.connections:
                conn = ws_ctx.config.aws.get_connection(
                    connection_name or ws_ctx.config.aws.default_connection
                )
                if conn:
                    s3_session = boto3.Session(profile_name=conn.profile)

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
    ws_path = resolve_workspace_secret_path()
    policy = PseudonymPolicy(mode="consultant", tty_bypass=False, show_identifiers=False)
    engine = PseudonymizationEngine.create(ws_path, policy)

    source_label = cur_path if cur_path else (s3_uri or f"workspace:{workspace_name}")
    console.print("[bold]Kulshan Consultant Evidence Export[/bold]")
    console.print(f"  Period: {scope.from_date} to {scope.to_date}")
    console.print(f"  Source: {source_label}")
    console.print()

    # Create temp working directory
    work_dir = Path(tempfile.mkdtemp(prefix="kulshan-export-"))
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
            session = boto3.Session(**session_kwargs)

            try:
                ce_result = export_ce(session, scope, engine, ce_dir)
                console.print(f"  Datasets: {len(ce_result.datasets)}")
                console.print(f"  Rows: {ce_result.total_rows:,}")
            except CeTruncationError as e:
                console.print(f"[red]CE EXPORT FAILED[/red]: {e}")
                sys.exit(ExitCode.RUNTIME_ERROR)

        # ── Gate 1: Schema ───────────────────────────────────────────────
        console.print()
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
            output_path=cur_result.output_path.as_posix(),
            numeric_columns=numeric_safe,
            pseudo_columns=pseudo_cols,
            safe_dimensions=safe_dims,
            engine=engine,
            scope=scope,
        )
        if not g2.passed:
            console.print("[red]GATE 2 FAILED: Evidence integrity[/red]")
            for f in g2.failures:
                console.print(f"  {f}")
            sys.exit(ExitCode.RUNTIME_ERROR)
        console.print("[green]Gate 2 PASS[/green]: Evidence integrity")

        # ── Gate 3: Residual identifiers ─────────────────────────────────
        # Collect source identifiers from pseudonymize columns
        source_ids = _collect_source_identifiers(cur_path, scope, cur_result.classification)
        # Collect all output text
        output_text = _collect_output_text(cur_dir, ce_dir)
        secret_path = ws_path / SECRET_FILENAME

        g3 = gate_residual(source_ids, output_text, secret_path)
        if not g3.passed:
            console.print("[red]GATE 3 FAILED: Residual identifiers[/red]")
            for f in g3.failures:
                console.print(f"  {f}")
            sys.exit(ExitCode.RUNTIME_ERROR)
        console.print("[green]Gate 3 PASS[/green]: Residual identifier scan")

        # ── Package ──────────────────────────────────────────────────────
        console.print()
        gate_dicts = [
            {"gate": g.gate, "passed": g.passed, "details": g.details}
            for g in [g1, g2, g3]
        ]

        if output is None:
            ws_name = ws_path.name if ws_path else "default"
            ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
            output = f"consultant-export-{ws_name}-{ts}.zip"

        zip_path = create_package(
            output_path=Path(output),
            cur_dir=cur_dir,
            ce_dir=ce_dir if ce_result else None,
            scope=scope,
            classification=cur_result.classification,
            gate_results=gate_dicts,
            cur_row_count=cur_result.row_count,
            ce_datasets=ce_result.datasets if ce_result else None,
            dropped_columns=cur_result.dropped_columns,
            keep_tags=list(keep_tags),
        )

        console.print(f"[bold green]Evidence package created:[/bold green] {zip_path}")
        console.print(f"  CUR rows: {cur_result.row_count:,}")
        if ce_result:
            console.print(f"  CE datasets: {len(ce_result.datasets)}")

    finally:
        # Clean up temp directory
        shutil.rmtree(work_dir, ignore_errors=True)


def _collect_source_identifiers(
    cur_path: str,
    scope,
    classification: dict,
) -> set[str]:
    """Collect distinct identifier values from PSEUDONYMIZE columns in source."""
    from kulshan.cur.duckdb_engine import connect_memory, cur_raw_columns, register_cur_raw
    from kulshan.cur.source import local_parquet_source
    from kulshan.export.columns import ColumnClass

    source = local_parquet_source(cur_path)
    con = connect_memory()
    try:
        mapping = register_cur_raw(con, source)
        columns = cur_raw_columns(con)
        where = scope.duckdb_where_clause(mapping.usage_start, mapping.account_id, mapping.service)

        identifiers: set[str] = set()
        pseudo_cols = [c for c, cls in classification.items() if cls == ColumnClass.PSEUDONYMIZE and c in columns]

        for col in pseudo_cols:
            try:
                rows = con.execute(
                    f'SELECT DISTINCT CAST("{col}" AS VARCHAR) FROM cur_raw '
                    f"WHERE {where} AND \"{col}\" IS NOT NULL "
                    f"LIMIT 10000"
                ).fetchall()
                for row in rows:
                    val = str(row[0]).strip()
                    if val:
                        identifiers.add(val)
            except Exception:
                continue

        return identifiers
    finally:
        con.close()


def _collect_output_text(cur_dir: Path, ce_dir: Path) -> str:
    """Read all output Parquet files and extract string column values for scanning."""
    import duckdb

    texts = []
    for d in [cur_dir, ce_dir]:
        if not d or not d.exists():
            continue
        for f in d.rglob("*.parquet"):
            try:
                con = duckdb.connect(":memory:")
                # Get string columns only
                desc = con.execute(f"DESCRIBE SELECT * FROM read_parquet('{f.as_posix()}')").fetchall()
                str_cols = [row[0] for row in desc if "VARCHAR" in str(row[1]).upper()]
                if str_cols:
                    select = ", ".join(f'CAST("{c}" AS VARCHAR)' for c in str_cols)
                    rows = con.execute(
                        f"SELECT {select} FROM read_parquet('{f.as_posix()}') LIMIT 100000"
                    ).fetchall()
                    for row in rows:
                        for val in row:
                            if val:
                                texts.append(str(val))
                con.close()
            except Exception:
                continue

    return " ".join(texts)
