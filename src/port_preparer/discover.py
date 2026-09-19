"""Assemble parsed command output into a `DeviceState`.

Precedence rules, which matter:

* **Configuration** comes from `show running-config` where available -- it is what the device
  will actually do, and it is the baseline for backup and rollback.
* **State** (link status, MTU, transceiver, MLT membership as programmed) comes from the show
  tables, because the running-config does not contain it.
* Bindings are taken from *both* and unioned, then any disagreement is recorded. A binding
  present in one source and not the other is exactly the kind of drift the audit exists to
  surface, so it is never silently reconciled.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from . import ports as portlib
from .collect import Collection
from .model import Binding, DeviceState, Isid, Mlt, Neighbor, Port, Vlan
from .parse import voss
from .parse.runconf import RunningConfig, parse_running_config

_ISID_TYPE_TO_KIND = {"ELAN": "elan", "CVLAN": "cvlan", "ELAN-TRANSPARENT": "elan-transparent"}


@dataclass
class DiscoveryReport:
    """What discovery could not make sense of. Surfaced in the audit, never swallowed."""

    skipped_lines: dict[str, list[str]] = field(default_factory=dict)
    unparsed_port_specs: list[str] = field(default_factory=list)
    binding_disagreements: list[str] = field(default_factory=list)

    @property
    def clean(self) -> bool:
        return not (self.skipped_lines or self.unparsed_port_specs or self.binding_disagreements)


def _port(state: DeviceState, port_id: str) -> Port:
    key = portlib.normalise(port_id) if portlib.is_port_id(port_id) else port_id
    return state.ports.setdefault(key, Port(port_id=key))


def _vlan(state: DeviceState, vid: int) -> Vlan:
    return state.vlans.setdefault(vid, Vlan(vid=vid))


def discover(collection: Collection) -> tuple[DeviceState, DiscoveryReport]:
    state = DeviceState(raw=dict(collection.raw), collection_errors=dict(collection.errors))
    report = DiscoveryReport()

    def note_skips(label: str, result: voss.ParseResult) -> voss.ParseResult:
        if result.skipped:
            report.skipped_lines[label] = result.skipped
        return result

    def text(command: str) -> str:
        return collection.raw.get(command, "")

    # --- configuration ------------------------------------------------------------
    running = parse_running_config(text("show running-config")) if text("show running-config") else RunningConfig()
    _apply_running_config(state, running, report)

    # --- VLANs --------------------------------------------------------------------
    for row in note_skips("show vlan basic", voss.parse_vlan_basic(text("show vlan basic"))).rows:
        vlan = _vlan(state, row["vid"])
        vlan.name = row["name"]
        vlan.vlan_type = row["vlan_type"]
        vlan.mstp_instance = row["mstp_instance"]

    for row in note_skips("show vlan i-sid", voss.parse_vlan_i_sid(text("show vlan i-sid"))).rows:
        vlan = _vlan(state, row["vid"])
        if row["i_sid"] is not None:
            vlan.i_sid = row["i_sid"]
            vlan.i_sid_name = row["i_sid_name"]

    member_rows = note_skips("show vlan members", voss.parse_vlan_members(text("show vlan members"))).rows
    if member_rows or any(v.members for v in running.vlans.values()):
        state.evidence.add("vlan-members")
    for row in member_rows:
        vlan = _vlan(state, row["vid"])
        static, bad_static = portlib.expand_tolerant(row["static_members"])
        active, bad_active = portlib.expand_tolerant(row["active_members"])
        report.unparsed_port_specs.extend(bad_static + bad_active)
        vlan.static_members = static
        vlan.active_members = active
        for port_id in static:
            port = _port(state, port_id)
            if row["vid"] not in port.vlan_members:
                port.vlan_members.append(row["vid"])

    # --- I-SIDs -------------------------------------------------------------------
    i_sid_rows = note_skips("show i-sid", voss.parse_i_sid(text("show i-sid"))).rows
    if i_sid_rows or running.isids:
        state.evidence.add("i-sid-bindings")
    for row in i_sid_rows:
        kind = _ISID_TYPE_TO_KIND.get(row["type"], row["type"].lower())
        isid = state.isids.get(row["i_sid"])
        if isid is None:
            isid = Isid(i_sid=row["i_sid"], kind=kind)
            state.isids[row["i_sid"]] = isid
        else:
            # The device's own TYPE column wins over what we inferred from the config block.
            isid.kind = kind
        isid.name = isid.name or row["name"]
        isid.origin = row["origin"]
        for interface, c_vid in row["port_bindings"]:
            if not portlib.is_port_id(interface):
                report.unparsed_port_specs.append(interface)
                continue
            pair = (portlib.normalise(interface), c_vid)
            if pair not in isid.port_bindings:
                isid.port_bindings.append(pair)
        for interface, c_vid in row["mlt_bindings"]:
            try:
                pair_mlt = (int(interface), c_vid)
            except ValueError:
                report.unparsed_port_specs.append(interface)
                continue
            if pair_mlt not in isid.mlt_bindings:
                isid.mlt_bindings.append(pair_mlt)

    # Per-port view of the same thing, used as a cross-check.
    port_isid_rows = note_skips(
        "show interfaces gigabitethernet i-sid",
        voss.parse_port_i_sid(text("show interfaces gigabitethernet i-sid")),
    ).rows

    # --- ports: state -------------------------------------------------------------
    interface_text = text("show interfaces gigabitethernet interface") or text("show interfaces gigabitethernet")
    for row in note_skips("show interfaces ... interface", voss.parse_port_interface(interface_text)).rows:
        port = _port(state, row["port_id"])
        port.transceiver = row["transceiver"]
        port.mtu = row["mtu"]
        port.admin = row["admin"]
        port.oper = row["oper"]

    combined = text("show interfaces gigabitethernet")
    for row in note_skips("show interfaces ... name", voss.parse_port_name(combined)).rows:
        port = _port(state, row["port_id"])
        port.name = row["name"] or port.name
        port.duplex = row["duplex"]
        port.speed = row["speed"]
        port.transceiver = port.transceiver or row["transceiver"]

    for row in note_skips("show interfaces ... config", voss.parse_port_config(combined)).rows:
        port = _port(state, row["port_id"])
        port.diffserv_enabled = row["diffserv_enabled"]
        port.qos_level = row["qos_level"]
        port.mlt_id = row["mlt_id"]

    # --- MLTs ---------------------------------------------------------------------
    for row in note_skips("show mlt", voss.parse_mlt(text("show mlt"))).rows:
        member_ports, bad = portlib.expand_tolerant(row.get("ports", ""))
        report.unparsed_port_specs.extend(bad)
        existing = state.mlts.get(row["mlt_id"])
        mlt = existing or Mlt(mlt_id=row["mlt_id"])
        mlt.name = row.get("name") or mlt.name
        mlt.ports = member_ports or mlt.ports
        mlt.port_type = row.get("port_type") or mlt.port_type
        mlt.smlt = row.get("smlt", mlt.smlt)
        mlt.lacp = row.get("lacp", mlt.lacp)
        mlt.flex_uni = row.get("flex_uni", mlt.flex_uni)
        mlt.dot1q = row.get("dot1q", mlt.dot1q)
        mlt.vlan_ids = row.get("vlan_ids", mlt.vlan_ids)
        state.mlts[row["mlt_id"]] = mlt
        for port_id in member_ports:
            port = _port(state, port_id)
            if port.mlt_id is None:
                port.mlt_id = row["mlt_id"]

    # --- fabric and redundancy ----------------------------------------------------
    for row in note_skips("show virtual-ist", voss.parse_virtual_ist(text("show virtual-ist"))).rows:
        state.vist_peer_ip = row["peer_ip"]
        state.vist_vlan = row["vlan_id"]

    dvr_rows = note_skips("show dvr interfaces", voss.parse_dvr_interfaces(text("show dvr interfaces"))).rows
    if dvr_rows:
        state.dvr_leaf = True

    for row in note_skips("show lldp neighbor summary", voss.parse_lldp_neighbor_summary(text("show lldp neighbor summary"))).rows:
        if not portlib.is_port_id(row["port_id"]):
            continue
        key = portlib.normalise(row["port_id"])
        state.neighbors[key] = Neighbor(
            port_id=key,
            sysname=row["sysname"],
            remote_port=row["remote_port"],
            sysdescr=row["sysdescr"],
            chassis_id=row["chassis_id"],
            mgmt_address=row["mgmt_address"],
        )

    # --- bindings: project I-SIDs onto ports, then cross-check --------------------
    _project_bindings(state)
    _cross_check_bindings(state, port_isid_rows, report)

    report.unparsed_port_specs = sorted(set(report.unparsed_port_specs))
    # One message per (port, i-sid): a port with both a tagged and an untagged binding on the
    # same I-SID would otherwise report the same drift twice.
    report.binding_disagreements = sorted(dict.fromkeys(report.binding_disagreements))
    return state, report


def _apply_running_config(state: DeviceState, running: RunningConfig, report: DiscoveryReport) -> None:
    state.hostname = running.hostname
    state.box_type = running.box_type
    state.software_version = running.software_version
    state.boot_flags = set(running.boot_flags)
    state.spbm_instance = running.spbm_instance
    state.spbm_nickname = running.spbm_nickname
    state.dvr_leaf = running.dvr_leaf
    report.unparsed_port_specs.extend(running.unparsed_port_specs)

    for vid, vlan_config in running.vlans.items():
        vlan = _vlan(state, vid)
        vlan.name = vlan_config.name or vlan.name
        vlan.vlan_type = vlan_config.vlan_type or vlan.vlan_type
        vlan.i_sid = vlan_config.i_sid or vlan.i_sid
        if vlan_config.mstp_instance is not None:
            vlan.mstp_instance = vlan_config.mstp_instance
        for port_id in vlan_config.members:
            if vid not in (port := _port(state, port_id)).vlan_members:
                port.vlan_members.append(vid)

    # B-VLANs are declared in `router isis` even when `show vlan basic` is unavailable.
    for b_vid in running.b_vids:
        vlan = _vlan(state, b_vid)
        vlan.vlan_type = vlan.vlan_type or "spbm-bvlan"

    for i_sid, isid_config in running.isids.items():
        state.isids[i_sid] = Isid(
            i_sid=i_sid,
            kind=isid_config.kind,
            name=isid_config.name,
            port_bindings=list(isid_config.port_bindings),
            mlt_bindings=list(isid_config.mlt_bindings),
            transparent_ports=list(isid_config.transparent_ports),
        )

    for mlt_id, mlt_config in running.mlts.items():
        state.mlts[mlt_id] = Mlt(
            mlt_id=mlt_id,
            name=mlt_config.name,
            smlt=mlt_config.smlt,
            lacp=mlt_config.lacp,
            lacp_key=mlt_config.lacp_key,
            flex_uni=mlt_config.flex_uni,
            dot1q=mlt_config.encapsulation_dot1q,
        )

    for port_id, port_config in running.port_configs.items():
        port = _port(state, port_id)
        port.name = port_config.name or port.name
        port.shutdown = port_config.shutdown
        port.encapsulation_dot1q = port_config.encapsulation_dot1q
        port.default_vlan_id = port_config.default_vlan_id
        port.flex_uni = port_config.flex_uni
        port.slpp_guard = port_config.slpp_guard
        port.slpp_guard_timeout = port_config.slpp_guard_timeout
        port.mstp_edge_port = port_config.mstp_edge_port
        port.auto_sense = port_config.auto_sense
        port.isis_enabled = port_config.isis_enabled
        port.config_lines = list(port_config.lines)


def _project_bindings(state: DeviceState) -> None:
    """Copy I-SID bindings onto the ports and MLTs they name."""
    for isid in state.isids.values():
        for port_id, c_vid in isid.port_bindings:
            port = _port(state, port_id)
            binding = Binding(i_sid=isid.i_sid, c_vid=c_vid)
            if binding not in port.bindings:
                port.bindings.append(binding)
        for mlt_id, c_vid in isid.mlt_bindings:
            mlt = state.mlts.setdefault(mlt_id, Mlt(mlt_id=mlt_id))
            binding = Binding(i_sid=isid.i_sid, c_vid=c_vid)
            if binding not in mlt.bindings:
                mlt.bindings.append(binding)
        for port_id in isid.transparent_ports:
            port = _port(state, port_id)
            if isid.i_sid not in port.transparent_i_sids:
                port.transparent_i_sids.append(isid.i_sid)

    # An MLT's bindings apply to every member port of that MLT.
    for mlt in state.mlts.values():
        for port_id in mlt.ports:
            port = _port(state, port_id)
            for binding in mlt.bindings:
                if binding not in port.bindings:
                    port.bindings.append(binding)


def _cross_check_bindings(state: DeviceState, port_isid_rows: list[dict], report: DiscoveryReport) -> None:
    """Compare `show interfaces ... i-sid` against what we derived, and record differences.

    Note that this table reports the *VLAN* a binding belongs to in its VLANID column and
    leaves C-VID as N/A in the captures we have, so only the (port, i-sid) pair is compared.
    """
    seen: set[tuple[str, int]] = set()
    for row in port_isid_rows:
        if not portlib.is_port_id(row["port_id"]):
            report.unparsed_port_specs.append(row["port_id"])
            continue
        key = portlib.normalise(row["port_id"])
        seen.add((key, row["i_sid"]))
        port = _port(state, key)
        if not any(b.i_sid == row["i_sid"] for b in port.bindings):
            c_vid = row["c_vid"] if row["c_vid"] is not None else row["vlan_id"]
            port.bindings.append(Binding(i_sid=row["i_sid"], c_vid=c_vid))
            report.binding_disagreements.append(
                f"{key}: i-sid {row['i_sid']} is reported by 'show interfaces gigabitethernet "
                f"i-sid' but was not found in the configuration or 'show i-sid'"
            )

    if not port_isid_rows:
        return
    for port in state.ports.values():
        for binding in port.bindings:
            if (port.port_id, binding.i_sid) not in seen and not port.in_mlt:
                report.binding_disagreements.append(
                    f"{port.port_id}: i-sid {binding.i_sid} is configured but does not appear in "
                    f"'show interfaces gigabitethernet i-sid'"
                )
