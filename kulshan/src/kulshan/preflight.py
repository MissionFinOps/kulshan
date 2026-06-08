"""Pre-flight health check for Kulshan scans."""
from __future__ import annotations

import sys
from typing import Any, List, Tuple

from rich.console import Console


def run_preflight(
    session: Any,
    console: Console | None = None,
) -> Tuple[bool, List[str]]:
    """Run pre-flight checks and print results.

    Returns (all_passed, list_of_warnings).
    If a critical check fails, returns (False, warnings).
    """
    if console is None:
        console = Console()

    warnings: List[str] = []
    all_passed = True

    console.print("\n  [bold]Pre-flight checks[/bold]")

    # 1. Python version
    py_version = sys.version_info
    if py_version >= (3, 9):
        console.print(f"  [green]✓[/green] Python {py_version.major}.{py_version.minor}")
    else:
        console.print(f"  [red]✗[/red] Python {py_version.major}.{py_version.minor} (need 3.9+)")
        all_passed = False

    # 2. AWS credentials exist
    try:
        credentials = session.get_credentials()
        if credentials is None:
            console.print("  [red]✗[/red] No AWS credentials found")
            console.print("    [dim]Run 'aws configure' or set AWS_ACCESS_KEY_ID[/dim]")
            all_passed = False
        else:
            console.print("  [green]✓[/green] AWS credentials found")
    except Exception as e:
        console.print(f"  [red]✗[/red] Credential error: {e}")
        all_passed = False

    # 3. STS identity (credentials not expired)
    try:
        sts = session.client("sts")
        identity = sts.get_caller_identity()
        account = identity.get("Account", "unknown")
        console.print(f"  [green]✓[/green] Authenticated (account {account})")
    except Exception as e:
        error_msg = str(e)
        if "ExpiredToken" in error_msg:
            console.print("  [red]✗[/red] Credentials expired")
            console.print("    [dim]Run 'aws sso login' or refresh your credentials[/dim]")
        elif "InvalidClientTokenId" in error_msg:
            console.print("  [red]✗[/red] Invalid credentials")
            console.print("    [dim]Check your AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY[/dim]")
        else:
            console.print(f"  [red]✗[/red] Auth failed: {error_msg[:80]}")
        all_passed = False

    # 4. Cost Explorer access (warning only, not critical)
    try:
        from datetime import date, timedelta
        probe_end = date.today()
        probe_start = probe_end - timedelta(days=2)
        ce = session.client("ce", region_name="us-east-1")
        ce.get_cost_and_usage(
            TimePeriod={"Start": probe_start.isoformat(), "End": probe_end.isoformat()},
            Granularity="DAILY",
            Metrics=["BlendedCost"],
        )
        console.print("  [green]✓[/green] Cost Explorer API accessible")
    except Exception as e:
        error_msg = str(e)
        if "not enabled" in error_msg.lower() or "OptIn" in error_msg:
            console.print("  [yellow]⚠[/yellow] Cost Explorer not enabled (cost pack will be empty)")
            warnings.append("Cost Explorer not enabled")
        elif "AccessDenied" in error_msg:
            console.print("  [yellow]⚠[/yellow] No Cost Explorer permission (cost pack may be limited)")
            warnings.append("No ce:GetCostAndUsage permission")
        else:
            console.print("  [yellow]⚠[/yellow] Cost Explorer check inconclusive")
            warnings.append(f"CE check: {error_msg[:60]}")

    console.print()
    return all_passed, warnings
