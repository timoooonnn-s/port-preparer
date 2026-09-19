"""Parser for `show running-config`.

The running-config is the authoritative view of *configuration* (the show tables are the
authoritative view of *state*), and it is what the backup/rollback path is built on, so this
parser keeps every line it attributes to an object verbatim as well as interpreting it.

One structural fact from real output matters: **VOSS emits port config in two passes.**
`encapsulation dot1q` appears in a `PORT CONFIGURATION - PHASE I` block and the rest of the
port's config in a separate `PHASE II` block for the same interface. So per-port state must
be *merged* across blocks, never taken from the first block found.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from .. import ports as portlib


@dataclass
class VlanConfig:
    vid: int
    name: str | None = None
    vlan_type: str | None = None
    mstp_instance: int | None = None
    i_sid: int | None = None
    members: list[str] = field(default_factory=list)


@dataclass
class IsidConfig:
    i_sid: int
    kind: str                                   # elan | elan-transparent
    name: str | None = None
    # (interface, c_vid) where c_vid None means untagged-traffic
    port_bindings: list[tuple[str, int | None]] = field(default_factory=list)
    mlt_bindings: list[tuple[int, int | None]] = field(default_factory=list)
    transparent_ports: list[str] = field(default_factory=list)
    lines: list[str] = field(default_factory=list)


@dataclass
class MltConfig:
    mlt_id: int
    name: str | None = None
    enabled: bool = False
    smlt: bool = False
    lacp: bool = False
    lacp_key: int | None = None
    flex_uni: bool = False
    encapsulation_dot1q: bool = False
    lines: list[str] = field(default_factory=list)


@dataclass
class PortConfig:
    port_id: str
    name: str | None = None
    shutdown: bool | None = None
    encapsulation_dot1q: bool = False
    default_vlan_id: int | None = None
    flex_uni: bool = False
    slpp_guard: bool = False
    slpp_guard_timeout: int | None = None
    mstp_edge_port: bool = False
    auto_sense: bool = False
    isis_enabled: bool = False
    isis_spbm_instance: int | None = None
    lines: list[str] = field(default_factory=list)


@dataclass
class RunningConfig:
    hostname: str | None = None
    box_type: str | None = None
    software_version: str | None = None
    cli_mode: str | None = None
    boot_flags: set[str] = field(default_factory=set)
    spbm_instance: int | None = None
    spbm_nickname: str | None = None
    b_vids: list[int] = field(default_factory=list)
    smlt_peer_system_id: str | None = None
    vlans: dict[int, VlanConfig] = field(default_factory=dict)
    isids: dict[int, IsidConfig] = field(default_factory=dict)
    mlts: dict[int, MltConfig] = field(default_factory=dict)
    port_configs: dict[str, PortConfig] = field(default_factory=dict)
    unparsed_port_specs: list[str] = field(default_factory=list)
    raw: str = ""

    @property
    def dvr_leaf(self) -> bool:
        return "dvr-leaf-mode" in self.boot_flags


_HEADER_FIELD = re.compile(r"^#\s*(?P<key>box type|software version|cli mode)\s*:\s*(?P<value>.+?)\s*$")
_INTERFACE_GIG = re.compile(r"^interface\s+gigabitethernet\s+(?P<spec>\S+)\s*$", re.IGNORECASE)
_INTERFACE_MLT = re.compile(r"^interface\s+mlt\s+(?P<id>\d+)\s*$", re.IGNORECASE)
_ISID_BLOCK = re.compile(r"^i-sid\s+(?P<isid>\d+)(?:\s+(?P<kind>elan-transparent|elan))?\s*$", re.IGNORECASE)
_NAMED = re.compile(r'^name\s+"?(?P<name>[^"]+)"?\s*$', re.IGNORECASE)


def _vlan(config: RunningConfig, vid: int) -> VlanConfig:
    return config.vlans.setdefault(vid, VlanConfig(vid=vid))


def parse_running_config(text: str) -> RunningConfig:  # noqa: C901 - a flat dispatch reads better here
    config = RunningConfig(raw=text)
    context: tuple[str, object] | None = None

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue

        if line.startswith("#"):
            match = _HEADER_FIELD.match(line)
            if match is not None:
                key, value = match["key"], match["value"]
                if key == "box type":
                    config.box_type = value
                elif key == "software version":
                    config.software_version = value
                else:
                    config.cli_mode = value
            continue

        # --- block entry ------------------------------------------------------------
        match = _INTERFACE_GIG.match(line)
        if match is not None:
            expanded, bad = portlib.expand_tolerant(match["spec"])
            config.unparsed_port_specs.extend(bad)
            for port_id in expanded:
                config.port_configs.setdefault(port_id, PortConfig(port_id=port_id))
            context = ("port", expanded)
            continue

        match = _INTERFACE_MLT.match(line)
        if match is not None:
            mlt_id = int(match["id"])
            config.mlts.setdefault(mlt_id, MltConfig(mlt_id=mlt_id))
            context = ("mlt", mlt_id)
            continue

        match = _ISID_BLOCK.match(line)
        if match is not None:
            i_sid = int(match["isid"])
            kind = (match["kind"] or "elan").lower()
            existing = config.isids.get(i_sid)
            if existing is None:
                config.isids[i_sid] = IsidConfig(i_sid=i_sid, kind=kind)
            context = ("isid", i_sid)
            continue

        if line.lower() == "router isis":
            context = ("isis", None)
            continue

        if line.lower() in {"exit", "end", "config terminal", "router ospf"}:
            context = None if line.lower() != "router ospf" else ("ospf", None)
            continue

        # --- inside a block ---------------------------------------------------------
        if context is not None:
            kind, target = context
            if kind == "port":
                for port_id in target:  # type: ignore[union-attr]
                    _apply_port_line(config.port_configs[port_id], line)
                continue
            if kind == "mlt":
                _apply_mlt_line(config.mlts[target], line)  # type: ignore[index]
                continue
            if kind == "isid":
                _apply_isid_line(config, config.isids[target], line)  # type: ignore[index]
                continue
            if kind == "isis":
                _apply_isis_line(config, line)
                continue
            if kind == "ospf":
                continue

        # --- global lines -----------------------------------------------------------
        _apply_global_line(config, line)

    return config


def _apply_global_line(config: RunningConfig, line: str) -> None:
    lowered = line.lower()

    if lowered.startswith("boot config flags "):
        config.boot_flags.add(line[len("boot config flags "):].strip())
        return

    match = re.match(r'^prompt\s+"?(?P<name>[^"]+)"?\s*$', line, re.IGNORECASE)
    if match is not None:
        config.hostname = match["name"]
        return

    match = re.match(
        r'^vlan\s+create\s+(?P<vid>\d+)(?:\s+name\s+"(?P<name>[^"]*)")?(?:\s+type\s+(?P<type>\S+))?'
        r"(?:\s+(?P<inst>\d+))?\s*$",
        line,
        re.IGNORECASE,
    )
    if match is not None:
        vlan = _vlan(config, int(match["vid"]))
        vlan.name = match["name"] or vlan.name
        vlan.vlan_type = match["type"] or vlan.vlan_type
        if match["inst"] is not None:
            vlan.mstp_instance = int(match["inst"])
        return

    match = re.match(r"^vlan\s+i-sid\s+(?P<vid>\d+)\s+(?P<isid>\d+)\s*$", line, re.IGNORECASE)
    if match is not None:
        _vlan(config, int(match["vid"])).i_sid = int(match["isid"])
        return

    match = re.match(
        r"^vlan\s+members\s+(?P<action>add|remove)\s+(?P<vid>\d+)\s+(?P<spec>\S+)", line, re.IGNORECASE
    )
    if match is not None:
        vlan = _vlan(config, int(match["vid"]))
        expanded, bad = portlib.expand_tolerant(match["spec"])
        config.unparsed_port_specs.extend(bad)
        if match["action"].lower() == "add":
            vlan.members = sorted(set(vlan.members) | set(expanded), key=portlib.parts)
        else:
            vlan.members = [p for p in vlan.members if p not in set(expanded)]
        return

    match = re.match(
        r'^mlt\s+(?P<id>\d+)\s+(?P<rest>.*)$', line, re.IGNORECASE
    )
    if match is not None:
        mlt = config.mlts.setdefault(int(match["id"]), MltConfig(mlt_id=int(match["id"])))
        rest = match["rest"]
        if re.search(r"\benable\b", rest, re.IGNORECASE):
            mlt.enabled = True
        name = re.search(r'name\s+"(?P<name>[^"]*)"', rest, re.IGNORECASE)
        if name is not None:
            mlt.name = name["name"]
        mlt.lines.append(line)
        return


def _apply_isis_line(config: RunningConfig, line: str) -> None:
    match = re.match(r"^spbm\s+(?P<inst>\d+)\s*$", line, re.IGNORECASE)
    if match is not None:
        config.spbm_instance = int(match["inst"])
        return
    match = re.match(r"^spbm\s+(?P<inst>\d+)\s+nick-name\s+(?P<nick>\S+)\s*$", line, re.IGNORECASE)
    if match is not None:
        config.spbm_nickname = match["nick"]
        return
    match = re.match(r"^spbm\s+\d+\s+b-vid\s+(?P<vids>[\d,\-]+)", line, re.IGNORECASE)
    if match is not None:
        vids: list[int] = []
        for token in match["vids"].split(","):
            if "-" in token:
                lo, _, hi = token.partition("-")
                vids.extend(range(int(lo), int(hi) + 1))
            elif token:
                vids.append(int(token))
        config.b_vids = sorted(set(vids))
        return
    match = re.match(r"^spbm\s+\d+\s+smlt-peer-system-id\s+(?P<sysid>\S+)", line, re.IGNORECASE)
    if match is not None:
        config.smlt_peer_system_id = match["sysid"]


def _apply_mlt_line(mlt: MltConfig, line: str) -> None:
    mlt.lines.append(line)
    lowered = line.lower()
    if lowered == "smlt":
        mlt.smlt = True
    elif lowered == "flex-uni enable":
        mlt.flex_uni = True
    elif lowered == "encapsulation dot1q":
        mlt.encapsulation_dot1q = True
    else:
        match = re.match(r"^lacp\s+enable(?:\s+key\s+(?P<key>\d+))?", line, re.IGNORECASE)
        if match is not None:
            mlt.lacp = True
            if match["key"]:
                mlt.lacp_key = int(match["key"])


def _apply_isid_line(config: RunningConfig, isid: IsidConfig, line: str) -> None:
    isid.lines.append(line)

    match = re.match(r"^c-vid\s+(?P<cvid>\d+)\s+(?P<kind>port|mlt)\s+(?P<target>\S+)\s*$", line, re.IGNORECASE)
    if match is not None:
        cvid = int(match["cvid"])
        if match["kind"].lower() == "mlt":
            isid.mlt_bindings.append((int(match["target"]), cvid))
        else:
            expanded, bad = portlib.expand_tolerant(match["target"])
            config.unparsed_port_specs.extend(bad)
            isid.port_bindings.extend((p, cvid) for p in expanded)
        return

    match = re.match(r"^untagged-traffic\s+(?P<kind>port|mlt)\s+(?P<target>\S+)\s*$", line, re.IGNORECASE)
    if match is not None:
        if match["kind"].lower() == "mlt":
            isid.mlt_bindings.append((int(match["target"]), None))
        else:
            expanded, bad = portlib.expand_tolerant(match["target"])
            config.unparsed_port_specs.extend(bad)
            isid.port_bindings.extend((p, None) for p in expanded)
        return

    match = re.match(r"^port\s+(?P<spec>\S+)\s*$", line, re.IGNORECASE)
    if match is not None:
        expanded, bad = portlib.expand_tolerant(match["spec"])
        config.unparsed_port_specs.extend(bad)
        isid.transparent_ports.extend(expanded)
        return

    named = _NAMED.match(line)
    if named is not None:
        isid.name = named["name"]


def _apply_port_line(port: PortConfig, line: str) -> None:
    port.lines.append(line)
    lowered = line.lower()

    if lowered == "encapsulation dot1q":
        port.encapsulation_dot1q = True
    elif lowered == "no encapsulation dot1q":
        port.encapsulation_dot1q = False
    elif lowered == "flex-uni enable":
        port.flex_uni = True
    elif lowered == "no flex-uni enable":
        port.flex_uni = False
    elif lowered == "no shutdown":
        port.shutdown = False
    elif lowered == "shutdown":
        port.shutdown = True
    elif lowered == "auto-sense enable":
        port.auto_sense = True
    elif lowered == "isis enable":
        port.isis_enabled = True
    elif lowered == "isis":
        pass
    else:
        match = re.match(r"^default-vlan-id\s+(?P<vid>\d+)\s*$", line, re.IGNORECASE)
        if match is not None:
            port.default_vlan_id = int(match["vid"])
            return
        match = re.match(r"^slpp-guard\s+enable(?:\s+timeout\s+(?P<timeout>\d+))?\s*$", line, re.IGNORECASE)
        if match is not None:
            port.slpp_guard = True
            if match["timeout"] is not None:
                port.slpp_guard_timeout = int(match["timeout"])
            return
        match = re.match(r"^spanning-tree\s+mstp\s+edge-port\s+(?P<value>true|false)\s*$", line, re.IGNORECASE)
        if match is not None:
            port.mstp_edge_port = match["value"].lower() == "true"
            return
        match = re.match(r"^isis\s+spbm\s+(?P<inst>\d+)\s*$", line, re.IGNORECASE)
        if match is not None:
            port.isis_spbm_instance = int(match["inst"])
            return
        named = _NAMED.match(line)
        if named is not None:
            port.name = named["name"]
