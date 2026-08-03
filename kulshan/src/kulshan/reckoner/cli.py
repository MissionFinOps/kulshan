"""Public Click adapters for the existing Reckoner engine."""
# ruff: noqa: E501

from __future__ import annotations

import json
from functools import wraps
from pathlib import Path

import click

from .allocation import CommitmentProfile, claim_class
from .contracts import ExecutionSource, FilterOperator, FilterSpec, PeriodSpec, QuerySpec
from .cost.semantics import ParquetSource, open_local_relation
from .explore import built_in_modules, module_by_id
from .investigations import built_in_investigations, execute_investigation
from .query import execute_query, inspect_query
from .renderers import render_csv, render_json, render_markdown
from .saved import load_saved_query, save_query
from .sessions import append_note, load_session, save_session, start_session
from .terminal import render_result

OUTPUT = click.Choice(["json", "csv", "markdown", "terminal"])


def _errors(fn):
    @wraps(fn)
    def call(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except (OSError, ValueError, KeyError, RuntimeError) as exc:
            raise click.ClickException(str(exc)) from exc

    return call


def _filter(text):
    separator = "!=" if "!=" in text else "="
    if separator not in text:
        raise click.BadParameter("expected DIMENSION=VALUE or DIMENSION!=VALUE")
    dimension, value = text.split(separator, 1)
    if not dimension or not value:
        raise click.BadParameter("filter dimension and value must not be empty")
    operator = FilterOperator.NOT_EQUALS if separator == "!=" else FilterOperator.EQUALS
    return FilterSpec(dimension, operator, (value,))


def _spec(metric, period, start, end, groupings, filters, exclusions):
    return QuerySpec(
        metric=metric,
        period=PeriodSpec(period, start=start, end=end),
        groupings=groupings,
        filters=tuple(map(_filter, filters)),
        exclusions=tuple(map(_filter, exclusions)),
        execution_source=ExecutionSource.LOCAL,
    )


def _query_options(with_path=True):
    def decorate(fn):
        for option in (
            click.option("--exclude", "exclusions", multiple=True),
            click.option("--filter", "filters", multiple=True),
            click.option("--grouping", "groupings", multiple=True),
            click.option("--end"),
            click.option("--start"),
            click.option("--period", required=True),
            click.option("--metric", required=True),
        ):
            fn = option(fn)
        if with_path:
            fn = click.option("--path", required=True, type=click.Path(exists=True))(fn)
        return fn

    return decorate


def _execute(path, query):
    source = ParquetSource((str(Path(path).resolve()),))
    with open_local_relation(source) as (connection, relation):
        return execute_query(connection, relation, query)


def _render(result, output):
    renderer = {"json": render_json, "csv": render_csv, "markdown": render_markdown}.get(output)
    if renderer:
        return renderer(result)
    try:
        return render_result(result)
    except AttributeError:
        names = [column.column_id for column in result.columns]
        rows = [" | ".join(str(row.get(name, "")) for name in names) for row in result.rows]
        return "\n".join([" | ".join(names), *rows, f"Total: {result.totals.get('value', 0)}"])


def _echo(result, output):
    text = _render(result, output)
    click.echo(text, nl=not text.endswith("\n"))


def register_reckoner_commands(group):
    """Register commands beneath ``kulshan query``."""

    @group.command("run")
    @_query_options()
    @click.option("--output", type=OUTPUT, default="terminal")
    @click.option("--explain", is_flag=True)
    @click.option("--show-sql", is_flag=True)
    @_errors
    def run(
        path, metric, period, start, end, groupings, filters, exclusions, output, explain, show_sql
    ):
        """Run a query against local Parquet billing data."""
        query = _spec(metric, period, start, end, groupings, filters, exclusions)
        result = _execute(path, query)
        if explain:
            click.echo(json.dumps(inspect_query(query, result).to_dict(), indent=2, sort_keys=True))
        elif show_sql:
            click.echo(result.generated_sql)
        else:
            _echo(result, output)

    @group.command("list")
    @click.option("--dir", "directory", type=click.Path(file_okay=False), default="queries")
    def list_queries(directory):
        """List saved query definitions."""
        for path in sorted(Path(directory).glob("*.json")):
            click.echo(path.stem)

    @group.command("save")
    @click.option("--name", required=True)
    @click.option("--dir", "directory", type=click.Path(file_okay=False), default="queries")
    @_query_options(with_path=False)
    @_errors
    def save(name, directory, metric, period, start, end, groupings, filters, exclusions):
        """Save a validated query definition."""
        target = Path(directory) / f"{name}.json"
        target.parent.mkdir(parents=True, exist_ok=True)
        save_query(_spec(metric, period, start, end, groupings, filters, exclusions), target)
        click.echo(target)

    @group.command("validate")
    @click.option("--file", "filename", required=True, type=click.Path(exists=True))
    @_errors
    def validate(filename):
        """Validate a saved query definition."""
        load_saved_query(filename)
        click.echo("valid")

    @group.command("inspect")
    @click.option("--file", "filename", required=True, type=click.Path(exists=True))
    @_errors
    def inspect(filename):
        """Print a saved query definition."""
        click.echo(json.dumps(load_saved_query(filename).to_dict(), indent=2, sort_keys=True))


@click.command("explore")
@click.option("--list", "listing", is_flag=True)
@click.option("--module", "module_id")
@click.option("--path", type=click.Path(exists=True))
@click.option("--output", type=OUTPUT, default="terminal")
@_errors
def explore_command(listing, module_id, path, output):
    """Run a noninteractive guided exploration."""
    if listing:
        for module in built_in_modules():
            click.echo(f"{module.module_id}\t{module.question}")
        return
    if not module_id or not path:
        raise click.UsageError("--module and --path are required unless --list is used")
    _echo(_execute(path, module_by_id(module_id).query_defaults), output)


def _session_file(directory, session_id):
    return Path(directory) / f"{session_id}.json"


def _identity(fn):
    return click.option("--dir", "directory", required=True, type=click.Path(file_okay=False))(
        click.option("--id", "session_id", required=True)(fn)
    )


@click.group("session")
def session_group():
    """Record local investigation sessions."""


@session_group.command("start")
@_identity
@_errors
def session_start(session_id, directory):
    """Start a session."""
    target = _session_file(directory, session_id)
    if target.exists():
        raise click.ClickException(f"session already exists: {session_id}")
    target.parent.mkdir(parents=True, exist_ok=True)
    save_session(start_session(session_id), target)
    click.echo(target)


@session_group.command("add-query")
@_identity
@_query_options()
@_errors
def session_add_query(
    session_id, directory, path, metric, period, start, end, groupings, filters, exclusions
):
    """Execute and add a query."""
    query = _spec(metric, period, start, end, groupings, filters, exclusions)
    _execute(path, query)
    target = _session_file(directory, session_id)
    session = load_session(target)
    session.add(query)
    save_session(session, target)
    click.echo("query added")


@session_group.command("add-note")
@_identity
@click.option("--note", required=True)
@_errors
def session_add_note(session_id, directory, note):
    """Add a note to the last query."""
    target = _session_file(directory, session_id)
    session = load_session(target)
    append_note(session, note)
    save_session(session, target)
    click.echo("note added")


@session_group.command("show")
@_identity
@_errors
def session_show(session_id, directory):
    """Show a session as JSON."""
    click.echo(json.dumps(load_session(_session_file(directory, session_id)).to_dict(), indent=2))


@session_group.command("export")
@_identity
@click.option("--output", type=click.Choice(["json", "markdown"]), default="markdown")
@_errors
def session_export(session_id, directory, output):
    """Export a session."""
    session = load_session(_session_file(directory, session_id))
    if output == "json":
        click.echo(json.dumps(session.to_dict(), indent=2, sort_keys=True))
        return
    lines = [f"# Investigation session: {session.session_id}", ""]
    for number, entry in enumerate(session.entries, 1):
        lines += [f"## Query {number}", "", f"- Metric: {entry.query.metric}"]
        if entry.note:
            lines.append(f"- Note: {entry.note}")
    click.echo("\n".join(lines))


@session_group.command("close")
@_identity
@_errors
def session_close(session_id, directory):
    """Close a session."""
    target = _session_file(directory, session_id)
    session = load_session(target)
    session.close()
    save_session(session, target)
    click.echo("session closed")


@click.command("investigate")
@click.option("--list", "listing", is_flag=True)
@click.option("--module", "module_id")
@click.option("--path", type=click.Path(exists=True))
@click.option("--output", type=OUTPUT, default="terminal")
@_errors
def investigate_command(listing, module_id, path, output):
    """Run a built-in cost investigation."""
    modules = built_in_investigations()
    if listing:
        for module in modules:
            click.echo(f"{module.module_id}\t{module.question}")
        return
    if not module_id or not path:
        raise click.UsageError("--module and --path are required unless --list is used")
    module = next((item for item in modules if item.module_id == module_id), None)
    if module is None:
        raise click.ClickException(f"unknown investigation module: {module_id}")
    with open_local_relation(ParquetSource((str(Path(path).resolve()),))) as (connection, relation):
        result = execute_investigation(connection, relation, module)
    _echo(result, output)


@click.group("commitment")
def commitment_group():
    """Analyze observed commitment charges."""


@commitment_group.command("analyze")
@click.option("--path", required=True, type=click.Path(exists=True))
@click.option("--output", type=click.Choice(["json", "terminal"]), default="terminal")
@_errors
def commitment_analyze(path, output):
    """Summarize commitment evidence."""
    source = ParquetSource((str(Path(path).resolve()),))
    with open_local_relation(source) as (connection, relation):
        rows = connection.execute(f'''SELECT coalesce(commitment_type, 'unknown'),
            SUM(CASE WHEN charge_category IN ('recurring-commitment-fee', 'upfront-commitment-fee')
                THEN coalesce(unblended_cost, 0) ELSE 0 END),
            SUM(CASE WHEN charge_category = 'unused-commitment' THEN coalesce(amortized_cost, 0) ELSE 0 END),
            SUM(coalesce(unblended_cost, 0)) FROM "{relation.relation_name}" GROUP BY 1 ORDER BY 1''').fetchall()
        schema = relation.source.source_type.value
    profiles = []
    for kind, fees, unused, total in rows:
        profile = CommitmentProfile(kind, None, None, float(fees), float(unused), schema)
        profiles.append(
            {
                "commitment_type": profile.commitment_type,
                "claim_class": claim_class(has_observed_cost=bool(total)).value,
                "coverage_ratio": profile.coverage_ratio,
                "utilization_ratio": profile.utilization_ratio,
                "fee_cost": profile.fee_cost,
                "unused_cost": profile.unused_cost,
                "source_schema": profile.source_schema,
                "limitations": list(profile.limitations),
            }
        )
    if output == "json":
        click.echo(json.dumps({"profiles": profiles}, indent=2, sort_keys=True))
    else:
        for profile in profiles:
            click.echo(f"{profile['commitment_type']}: {profile['claim_class']}")


def register_top_level_reckoner_commands(group):
    """Register top-level Reckoner commands."""
    for command in (explore_command, session_group, investigate_command, commitment_group):
        group.add_command(command)
