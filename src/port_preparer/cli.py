"""Command line interface.

Phase 1 ships two read-only commands:

* `audit`   -- report on a device's ports, either live or from a capture.
* `capture` -- run the collection and save the raw output, in the layout the test suite reads.

`capture` exists so that a lab run produces fixtures: output we have never seen (T-UNI, 9.4
releases, management switches) reaches the test suite only this way.

Credentials are prompted for and held in memory. Nothing is written to disk but the capture.
"""

from __future__ import annotations

import getpass
import json
import os
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from .audit import AuditResult, Severity, audit
from .collect import AUDIT_COMMANDS, Collection, collect
from .conventions import Environment, classify_isid, decode_vlan_name, isid_for_new_service, mlt_id_for_new_lag
from .discover import DiscoveryReport, discover
from .model import DeviceState
from .profiles import ProfileSet
from .transport import MockTransport, SSHTransport, Transport, TransportError

app = typer.Typer(
    add_completion=False,
    help="Create and audit configured access ports on Extreme VOSS / Fabric Connect switches.",
    no_args_is_help=True,
)
console = Console()

_SEVERITY_STYLE = {
    Severity.ERROR: "bold red",
    Severity.WARNING: "yellow",
    Severity.UNKNOWN: "magenta",
    Severity.LEGACY: "dim cyan",
    Severity.INFO: "dim",
}


def _open_transport(host: str | None, capture: Path | None, username: str | None) -> Transport:
    if capture is not None and host is not None:
        raise typer.BadParameter("give either --host or --capture, not both")
    if capture is not None:
        return MockTransport(capture)
    if host is None:
        raise typer.BadParameter("one of --host or --capture is required")

    user = username or os.environ.get("USER") or ""
    user = typer.prompt("Username", default=user) if not username else username
    # RADIUS credentials: prompted per run, never stored, never written anywhere.
    password = getpass.getpass(f"Password for {user}@{host}: ")
    return SSHTransport(host, user, password)


def _gather(transport: Transport) -> tuple[Collection, DeviceState, DiscoveryReport]:
    collection = collect(transport, AUDIT_COMMANDS)
    state, report = discover(collection)
    return collection, state, report


def _render(result: AuditResult, show_info: bool) -> None:
    state = result.state
    console.print()
    console.print(
        f"[bold]{result.host}[/bold]  "
        f"{state.box_type or 'platform unknown'}  "
        f"{state.software_version or 'release unknown'}"
        + (f"  [cyan]DVR leaf[/cyan]" if state.dvr_leaf else "")
        + (f"  [cyan]vIST peer {state.vist_peer_ip}[/cyan]" if state.vist_peer_ip else "")
    )
    console.print(f"[dim]profile layers: {' -> '.join(result.profile.layers)}[/dim]")

    ports = Table(title="Ports", title_justify="left", header_style="bold")
    for column in ("Port", "Model", "Link", "MLT", "Bindings / VLANs", "Neighbour"):
        ports.add_column(column, overflow="fold")
    for port_id in sorted(state.ports, key=lambda p: [int(x) for x in p.split("/")] if "/" in p else [0]):
        port = state.ports[port_id]
        model = state.uni_model(port_id)
        services = [str(b) for b in port.bindings] or [f"vlan {v}" for v in port.vlan_members]
        neighbour = state.neighbors.get(port_id)
        ports.add_row(
            port_id,
            model.value,
            f"{port.admin or '?'}/{port.oper or '?'}",
            str(port.mlt_id or ""),
            ", ".join(services),
            (neighbour.sysname or neighbour.sysdescr or "") if neighbour else "",
        )
    console.print(ports)

    findings = [f for f in result.sorted_findings() if show_info or f.severity is not Severity.INFO]
    if findings:
        table = Table(title="Findings", title_justify="left", header_style="bold")
        for column in ("Severity", "Scope", "Code", "Detail"):
            table.add_column(column, overflow="fold")
        for finding in findings:
            style = _SEVERITY_STYLE[finding.severity]
            table.add_row(
                f"[{style}]{finding.severity.value}[/{style}]", finding.scope, finding.code, finding.message
            )
        console.print(table)

    counts = result.counts
    summary = "  ".join(f"{name}: {count}" for name, count in sorted(counts.items())) or "nothing to report"
    console.print(f"\n{summary}")
    if not show_info and any(f.severity is Severity.INFO for f in result.findings):
        console.print("[dim]informational findings hidden; pass --info to show them[/dim]")


def _as_dict(result: AuditResult) -> dict:
    state = result.state
    return {
        "host": result.host,
        "hostname": state.hostname,
        "box_type": state.box_type,
        "software_version": state.software_version,
        "dvr_leaf": state.dvr_leaf,
        "vist": {"peer": state.vist_peer_ip, "vlan": state.vist_vlan},
        "b_vlans": state.bvlans,
        "missing_evidence": sorted(state.missing_evidence),
        "profile_layers": result.profile.layers,
        "ports": {
            port_id: {
                "model": state.uni_model(port_id).value,
                "admin": port.admin,
                "oper": port.oper,
                "mlt_id": port.mlt_id,
                "name": port.name,
                "mtu": port.mtu,
                "bindings": [{"i_sid": b.i_sid, "c_vid": b.c_vid} for b in port.bindings],
                "vlan_members": port.vlan_members,
                "reserved_reason": state.reserved_reason(port_id),
            }
            for port_id, port in state.ports.items()
        },
        "findings": [
            {"severity": f.severity.value, "code": f.code, "scope": f.scope, "message": f.message}
            for f in result.sorted_findings()
        ],
        "counts": result.counts,
        "ok": result.ok,
    }


@app.command("audit")
def audit_device(
    host: str | None = typer.Option(None, "--host", "-H", help="Switch to connect to over SSH."),
    capture: Path | None = typer.Option(None, "--capture", "-c", help="Directory of captured show output."),
    username: str | None = typer.Option(None, "--username", "-u", help="Login name; prompted if omitted."),
    profile_path: Path | None = typer.Option(None, "--profile", help="Profile YAML; the built-in default if omitted."),
    site_category: str | None = typer.Option(None, "--site-category", help="dc | office | branch."),
    site: str | None = typer.Option(None, "--site", help="Site name, if the profile defines one."),
    scenario: str | None = typer.Option(None, "--scenario", help="Scenario to audit against."),
    save_raw: Path | None = typer.Option(None, "--save-raw", help="Also save the raw output to this directory."),
    as_json: bool = typer.Option(False, "--json", help="Emit machine-readable output instead of tables."),
    show_info: bool = typer.Option(False, "--info", help="Include informational findings."),
) -> None:
    """Audit a device's ports. Read-only: nothing is written to the switch."""
    try:
        transport = _open_transport(host, capture, username)
    except TransportError as exc:
        console.print(f"[bold red]{exc}[/bold red]")
        raise typer.Exit(code=2) from exc

    with transport:
        collection, state, report = _gather(transport)

    if save_raw is not None:
        target = collection.save(save_raw / (state.hostname or collection.host))
        console.print(f"[dim]raw output saved to {target}[/dim]")

    profiles = ProfileSet.load(profile_path) if profile_path else ProfileSet.load()
    result = audit(
        state, report, profiles=profiles, site_category=site_category, site=site,
        scenario=scenario, host=state.hostname or collection.host,
    )

    if as_json:
        console.print_json(json.dumps(_as_dict(result)))
    else:
        _render(result, show_info)

    raise typer.Exit(code=0 if result.ok else 1)


@app.command()
def capture(
    host: str = typer.Option(..., "--host", "-H", help="Switch to capture from."),
    output: Path = typer.Option(..., "--output", "-o", help="Directory to write the capture into."),
    username: str | None = typer.Option(None, "--username", "-u"),
) -> None:
    """Collect raw show output and save it in the layout the test suite reads.

    This is how output we have never seen becomes a fixture. Run it against anything unusual
    -- a T-UNI port, a 9.4 box, a management switch -- and the capture can be committed.
    """
    try:
        transport = _open_transport(host, None, username)
    except TransportError as exc:
        console.print(f"[bold red]{exc}[/bold red]")
        raise typer.Exit(code=2) from exc

    with transport:
        collection = collect(transport, AUDIT_COMMANDS)

    target = collection.save(output)
    console.print(f"saved {len(collection.raw)} command outputs to {target}")
    for command, message in sorted(collection.errors.items()):
        console.print(f"[yellow]{command}: {message}[/yellow]")
    console.print(
        "\n[bold]Before committing a capture, remove hostnames.[/bold] Replace them with "
        "strings of the SAME LENGTH -- several tables are parsed by column offset, so changing "
        "a name's width corrupts the fixture."
    )


@app.command()
def conventions(
    vlan: int | None = typer.Option(None, "--vlan", help="Show the I-SID this VLAN would get."),
    environment: str = typer.Option("prod", "--environment", "-e", help="prod | nonprod | special."),
    i_sid: int | None = typer.Option(None, "--isid", help="Decompose an existing I-SID."),
    vlan_name: str | None = typer.Option(None, "--vlan-name", help="Decode a VLAN name."),
    port: str | None = typer.Option(None, "--port", help="Show the MLT id a new LAG on this port would get."),
) -> None:
    """Explain or compute the estate's naming and numbering conventions."""
    if vlan is not None:
        try:
            env = Environment(environment)
            console.print(f"VLAN {vlan} in {env.value} -> i-sid {isid_for_new_service(vlan, env)}")
        except ValueError as exc:
            console.print(f"[bold red]{exc}[/bold red]")
            raise typer.Exit(code=2) from exc
    if i_sid is not None:
        decoded = classify_isid(i_sid)
        console.print(
            f"i-sid {i_sid}: prefix {decoded.prefix}, environment "
            f"{decoded.environment.value if decoded.environment else 'unknown'}, vlan {decoded.vlan_id}, "
            f"canonical={decoded.canonical}" + (f" ({decoded.note})" if decoded.note else "")
        )
    if vlan_name is not None:
        decoded_name = decode_vlan_name(vlan_name)
        if decoded_name is None:
            console.print(f"{vlan_name!r} does not follow the VLAN-name convention")
        else:
            console.print(
                f"{vlan_name} -> network {decoded_name.network}, leading letter "
                f"{decoded_name.letter!r} (meaning still unknown -- open question Q3)"
            )
    if port is not None:
        try:
            console.print(f"a new LAG on {port} -> MLT {mlt_id_for_new_lag(port)}")
        except ValueError as exc:
            console.print(f"[bold red]{exc}[/bold red]")
            raise typer.Exit(code=2) from exc
    if all(x is None for x in (vlan, i_sid, vlan_name, port)):
        console.print("pass one of --vlan, --isid, --vlan-name or --port")


def main() -> None:  # pragma: no cover - entry point
    app()


if __name__ == "__main__":  # pragma: no cover
    main()
