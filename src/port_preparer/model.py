"""Domain model.

Two constraints from council decisions 0004 and the fixture review drive every type here:

1. A port holds a *list of bindings*, not a tagging mode. Real config shows one port
   carrying I-SID 2500695 as both `c-vid 695` and `untagged-traffic` while also carrying
   I-SID 2510735 as `c-vid 735`.
2. Port identifiers are opaque strings with two *or three* parts (`1/45`, `2/1/1`). Nothing
   here parses them as slot/port.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class UniModel(str, Enum):
    """How a port attaches to a service. Detected, never assumed (decision 0003)."""

    SWITCHED = "switched-uni"       # flex-uni, `i-sid <x> elan` + c-vid/untagged bindings
    CVLAN = "platform-vlan"         # classic: vlan i-sid + vlan members
    TRANSPARENT = "t-uni"           # `i-sid <x> elan-transparent`
    NNI = "nni"                     # ISIS fabric link, not a UNI at all
    UNUSED = "unused"               # no service on the port
    UNKNOWN = "unknown"             # the evidence needed to decide was not collected
    MIXED = "mixed"                 # both models present: refuse to touch


class Environment(str, Enum):
    PROD = "prod"
    NONPROD = "nonprod"
    SPECIAL = "special"
    INFRA = "infra"                 # vIST, B-VLANs: reserved, never generated


@dataclass(frozen=True)
class Binding:
    """One I-SID attachment on a port or MLT.

    `c_vid is None` means `untagged-traffic`; otherwise it is a `c-vid <n>` binding.
    """

    i_sid: int
    c_vid: int | None

    @property
    def untagged(self) -> bool:
        return self.c_vid is None

    def __str__(self) -> str:
        return f"i-sid {self.i_sid} {'untagged' if self.untagged else f'c-vid {self.c_vid}'}"


@dataclass
class Vlan:
    vid: int
    name: str | None = None
    vlan_type: str | None = None          # byPort, spbm-bvlan, port-mstprstp ...
    i_sid: int | None = None
    i_sid_name: str | None = None
    mstp_instance: int | None = None
    static_members: list[str] = field(default_factory=list)
    active_members: list[str] = field(default_factory=list)

    @property
    def is_bvlan(self) -> bool:
        return (self.vlan_type or "").lower() == "spbm-bvlan"


@dataclass
class Isid:
    i_sid: int
    kind: str                             # elan | elan-transparent | cvlan
    name: str | None = None
    origin: str | None = None
    # (port_id, c_vid) with c_vid None for untagged-traffic
    port_bindings: list[tuple[str, int | None]] = field(default_factory=list)
    mlt_bindings: list[tuple[int, int | None]] = field(default_factory=list)
    transparent_ports: list[str] = field(default_factory=list)

    @property
    def is_switched_uni(self) -> bool:
        return self.kind == "elan"

    @property
    def is_transparent(self) -> bool:
        return self.kind == "elan-transparent"


@dataclass
class Mlt:
    mlt_id: int
    name: str | None = None
    ports: list[str] = field(default_factory=list)
    port_type: str | None = None          # trunk | access
    smlt: bool = False
    lacp: bool = False
    lacp_key: int | None = None
    flex_uni: bool = False
    dot1q: bool = False
    vlan_ids: list[int] = field(default_factory=list)
    bindings: list[Binding] = field(default_factory=list)


@dataclass
class Port:
    """State of one physical port, as read off the switch."""

    port_id: str
    # operational / inventory
    admin: str | None = None
    oper: str | None = None
    mtu: int | None = None
    transceiver: str | None = None        # the DESCRIPTION column: read-only, not a name
    name: str | None = None               # set only on uplinks/infra in this estate
    duplex: str | None = None
    speed: int | None = None
    qos_level: int | None = None
    diffserv_enabled: bool | None = None
    # configuration
    shutdown: bool | None = None
    encapsulation_dot1q: bool = False
    default_vlan_id: int | None = None
    flex_uni: bool = False
    slpp_guard: bool = False
    slpp_guard_timeout: int | None = None
    mstp_edge_port: bool = False
    auto_sense: bool = False
    isis_enabled: bool = False
    mlt_id: int | None = None
    # services
    bindings: list[Binding] = field(default_factory=list)
    vlan_members: list[int] = field(default_factory=list)
    transparent_i_sids: list[int] = field(default_factory=list)
    # everything the running-config said about this interface, verbatim
    config_lines: list[str] = field(default_factory=list)

    @property
    def in_mlt(self) -> bool:
        return self.mlt_id is not None and self.mlt_id != 0


@dataclass
class SpbmIsid:
    """An I-SID as the ISIS control plane sees it, from `show isis spbm i-sid all`.

    `locally_configured` means this switch configures it. `advertised_by` lists the remote BEBs
    that announce it. An I-SID configured here with nobody advertising it has no far end -- which
    is how an orphan is detected without crawling the fabric.
    """

    i_sid: int
    locally_configured: bool = False
    advertised_by: list[str] = field(default_factory=list)
    b_vids: list[int] = field(default_factory=list)

    @property
    def has_remote_endpoint(self) -> bool:
        return bool(self.advertised_by)


@dataclass
class Neighbor:
    port_id: str
    sysname: str | None
    remote_port: str | None
    sysdescr: str | None
    chassis_id: str | None = None
    mgmt_address: str | None = None


@dataclass
class DeviceState:
    """Everything the tool knows about one switch after a collection pass."""

    hostname: str | None = None
    box_type: str | None = None
    software_version: str | None = None
    boot_flags: set[str] = field(default_factory=set)
    ports: dict[str, Port] = field(default_factory=dict)
    vlans: dict[int, Vlan] = field(default_factory=dict)
    isids: dict[int, Isid] = field(default_factory=dict)
    mlts: dict[int, Mlt] = field(default_factory=dict)
    neighbors: dict[str, Neighbor] = field(default_factory=dict)
    spbm_isids: dict[int, SpbmIsid] = field(default_factory=dict)
    vist_peer_ip: str | None = None
    vist_vlan: int | None = None
    spbm_instance: int | None = None
    spbm_nickname: str | None = None
    dvr_leaf: bool = False
    raw: dict[str, str] = field(default_factory=dict)
    # commands whose collection failed, so the audit can say "unknown" instead of "absent"
    collection_errors: dict[str, str] = field(default_factory=dict)
    #: Which classes of evidence the collection actually produced. Absence of evidence is
    #: never reported as absence of configuration -- see `uni_model`.
    evidence: set[str] = field(default_factory=set)

    # -- derived ----------------------------------------------------------------

    @property
    def bvlans(self) -> list[int]:
        return sorted(v.vid for v in self.vlans.values() if v.is_bvlan)

    #: Evidence classes `uni_model` needs before it may call a port unused.
    REQUIRED_EVIDENCE = frozenset({"vlan-members", "i-sid-bindings"})

    def uni_model(self, port_id: str) -> UniModel:
        """Which model this specific port speaks. See KB entry 01.

        Returns `UNKNOWN` rather than `UNUSED` when the collection did not include the
        commands that would reveal a service. A tool that reports "this port is free" because
        it failed to ask is worse than one that admits it does not know.
        """
        port = self.ports.get(port_id)
        if port is not None:
            if port.isis_enabled:
                return UniModel.NNI
            if port.transparent_i_sids:
                return UniModel.TRANSPARENT
            service_vlans = [v for v in port.vlan_members if self._is_service_vlan(v)]
            switched = bool(port.bindings) or port.flex_uni
            if switched and service_vlans:
                return UniModel.MIXED
            if switched:
                return UniModel.SWITCHED
            if service_vlans:
                return UniModel.CVLAN
        if not self.REQUIRED_EVIDENCE <= self.evidence:
            return UniModel.UNKNOWN
        return UniModel.UNUSED

    @property
    def missing_evidence(self) -> set[str]:
        return set(self.REQUIRED_EVIDENCE) - self.evidence

    def _is_service_vlan(self, vid: int) -> bool:
        """A VLAN that represents a tenant service, as opposed to infrastructure."""
        vlan = self.vlans.get(vid)
        if vlan is None:
            return vid != 1
        if vlan.is_bvlan or vid == 1:
            return False
        return vid != self.vist_vlan

    def reserved_reason(self, port_id: str) -> str | None:
        """Why the tool must refuse to touch this port, or None if it is fair game."""
        port = self.ports.get(port_id)
        if port is None:
            return None
        if port.isis_enabled:
            return "ISIS/NNI fabric link"
        if port.auto_sense:
            return "auto-sense enabled (ZTP owns this port)"
        for vid in port.vlan_members:
            vlan = self.vlans.get(vid)
            if vlan is not None and vlan.is_bvlan:
                return f"member of SPBM B-VLAN {vid}"
            if vid == self.vist_vlan:
                return f"member of the vIST VLAN {vid}"
        mlt = self.mlts.get(port.mlt_id) if port.in_mlt else None
        if mlt is not None and any(
            (self.vlans.get(v).is_bvlan if self.vlans.get(v) else False) for v in mlt.vlan_ids
        ):
            return f"member of MLT {mlt.mlt_id}, which carries B-VLANs (vIST NNI)"
        return None
