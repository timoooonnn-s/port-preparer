"""Read-only compliance audit.

Phase 1 of the plan, and deliberately first: it has zero blast radius, and running it across
300 switches validates the data model against reality before the tool ever writes a line.

The severity scale exists because the estate is older than its own conventions. A port that
does not follow a rule introduced after it was built is **legacy**, not an error. Conflating
those two would report the whole estate as broken and the tool would be ignored, which the
Operator regards as the most likely way for this project to fail.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from . import conventions
from .discover import DiscoveryReport
from .model import DeviceState, UniModel
from .profiles import ProfileSet, ResolvedProfile


class Severity(str, Enum):
    ERROR = "error"          # actively wrong or dangerous; a human must look
    WARNING = "warning"      # drift, or a convention broken after the rule existed
    LEGACY = "legacy"        # predates the current convention; not a defect
    UNKNOWN = "unknown"      # we could not determine this, and say so
    INFO = "info"            # context worth printing

    @property
    def rank(self) -> int:
        return {"error": 0, "warning": 1, "unknown": 2, "legacy": 3, "info": 4}[self.value]


@dataclass(frozen=True)
class Finding:
    severity: Severity
    code: str
    message: str
    port_id: str | None = None

    @property
    def scope(self) -> str:
        return self.port_id or "device"


@dataclass
class AuditResult:
    host: str
    state: DeviceState
    profile: ResolvedProfile
    findings: list[Finding] = field(default_factory=list)

    def by_severity(self, severity: Severity) -> list[Finding]:
        return [f for f in self.findings if f.severity is severity]

    @property
    def counts(self) -> dict[str, int]:
        out: dict[str, int] = {}
        for finding in self.findings:
            out[finding.severity.value] = out.get(finding.severity.value, 0) + 1
        return out

    @property
    def ok(self) -> bool:
        """True when nothing needs a human. Legacy and info do not block."""
        return not (self.by_severity(Severity.ERROR) or self.by_severity(Severity.WARNING))

    def sorted_findings(self) -> list[Finding]:
        return sorted(self.findings, key=lambda f: (f.severity.rank, f.scope, f.code))


def audit(
    state: DeviceState,
    report: DiscoveryReport,
    *,
    profiles: ProfileSet | None = None,
    site_category: str | None = None,
    site: str | None = None,
    scenario: str | None = None,
    host: str | None = None,
) -> AuditResult:
    profile_set = profiles or ProfileSet.load()
    role = profile_set.role_for_hostname(state.hostname or host)
    resolved = profile_set.resolve(site_category=site_category, site=site, role=role, scenario=scenario)

    result = AuditResult(host=host or state.hostname or "unknown", state=state, profile=resolved)
    add = result.findings.append

    _audit_device(state, report, add, role)
    _audit_vlans(state, add)
    _audit_mlts(state, add)
    for port_id in sorted(state.ports, key=_port_sort_key):
        _audit_port(state, port_id, resolved, add)
    return result


def _port_sort_key(port_id: str) -> tuple:
    try:
        from . import ports as portlib

        return (0, portlib.parts(port_id))
    except Exception:
        return (1, port_id)


def _audit_device(state: DeviceState, report: DiscoveryReport, add, role: str | None) -> None:
    if state.software_version:
        add(Finding(Severity.INFO, "release", f"{state.box_type or 'unknown platform'} running {state.software_version}"))
    else:
        add(Finding(
            Severity.UNKNOWN, "release",
            "software version unknown: no running-config was collected, so release-gated checks were skipped",
        ))

    if role:
        add(Finding(Severity.INFO, "role", f"hostname matches the {role} role"))

    if state.dvr_leaf:
        add(Finding(
            Severity.INFO, "dvr-leaf",
            "DVR leaf mode is enabled on this node; DVR restricts what may be configured and "
            "the apply path must account for it",
        ))

    if state.vist_vlan is not None:
        add(Finding(
            Severity.INFO, "vist",
            f"vIST peer {state.vist_peer_ip} on VLAN {state.vist_vlan}; this node is half of an "
            "SMLT pair, so dual-homed ports must be configured on both peers",
        ))

    for missing in sorted(state.missing_evidence):
        add(Finding(
            Severity.UNKNOWN, "missing-evidence",
            f"no {missing} data was collected, so ports with no detected service are reported "
            "as unknown rather than free",
        ))

    for command, message in sorted(state.collection_errors.items()):
        severity = Severity.INFO if "optional" in message else Severity.WARNING
        add(Finding(severity, "collection", f"{command}: {message}"))

    for label, lines in sorted(report.skipped_lines.items()):
        add(Finding(
            Severity.WARNING, "unparsed-output",
            f"{label}: {len(lines)} line(s) were not understood by the parser, so this device's "
            f"report may be incomplete. First: {lines[0].strip()!r}",
        ))

    for spec in report.unparsed_port_specs:
        add(Finding(Severity.WARNING, "unparsed-port-spec", f"could not expand the port specification {spec!r}"))

    for message in report.binding_disagreements:
        add(Finding(Severity.WARNING, "binding-drift", message))


def _audit_vlans(state: DeviceState, add) -> None:
    for vid, vlan in sorted(state.vlans.items()):
        if vlan.is_bvlan or vid in conventions.RESERVED_VLAN_IDS:
            continue

        if vlan.i_sid is not None:
            decoded = conventions.classify_isid(vlan.i_sid)
            if decoded.environment is None:
                add(Finding(
                    Severity.WARNING, "isid-prefix",
                    f"VLAN {vid} uses I-SID {vlan.i_sid}, whose prefix {decoded.prefix} is not a "
                    f"known environment prefix ({decoded.note})",
                ))
            elif decoded.environment is conventions.Environment.INFRA:
                add(Finding(
                    Severity.INFO, "isid-infra",
                    f"VLAN {vid} uses infrastructure I-SID {vlan.i_sid}; this tool never generates these",
                ))
            elif not conventions.isid_matches_vlan(vlan.i_sid, vid):
                add(Finding(
                    Severity.WARNING, "isid-vlan-mismatch",
                    f"VLAN {vid} is mapped to I-SID {vlan.i_sid}, which encodes VLAN "
                    f"{decoded.vlan_id} -- the convention is <prefix><vlan padded to 4>",
                ))
            elif not decoded.canonical:
                add(Finding(
                    Severity.LEGACY, "isid-prefix-variant",
                    f"VLAN {vid} uses I-SID {vlan.i_sid}: {decoded.note}",
                ))

        if vlan.name:
            if conventions.decode_vlan_name(vlan.name) is None:
                add(Finding(
                    Severity.LEGACY, "vlan-name",
                    f"VLAN {vid} is named {vlan.name!r}, which does not follow the "
                    "<LETTER><12-digit network>_<prefixlen> convention",
                ))


def _audit_mlts(state: DeviceState, add) -> None:
    for mlt_id, mlt in sorted(state.mlts.items()):
        if any((state.vlans.get(v).is_bvlan if state.vlans.get(v) else False) for v in mlt.vlan_ids):
            add(Finding(Severity.INFO, "mlt-nni", f"MLT {mlt_id} carries B-VLANs and is the vIST NNI; reserved"))
            continue

        if mlt.lacp and mlt.lacp_key is not None and mlt.lacp_key != conventions.lacp_key_for(mlt_id):
            add(Finding(
                Severity.WARNING, "lacp-key",
                f"MLT {mlt_id} has LACP key {mlt.lacp_key}; the convention is for the key to equal "
                "the MLT id",
            ))

        if conventions.is_legacy_mlt_id(mlt_id):
            add(Finding(
                Severity.LEGACY, "mlt-id",
                f"MLT {mlt_id} is outside the 4xx block used for new LAGs",
            ))
        elif len(mlt.ports) == 1 and not conventions.mlt_id_matches_port(mlt_id, mlt.ports[0]):
            add(Finding(
                Severity.WARNING, "mlt-id-port",
                f"MLT {mlt_id} is in the 4xx block but does not encode its member port "
                f"{mlt.ports[0]} (the convention gives "
                f"{conventions.mlt_id_for_new_lag(mlt.ports[0]) if '/' in mlt.ports[0] else '?'})",
            ))


def _audit_port(state: DeviceState, port_id: str, profile: ResolvedProfile, add) -> None:
    port = state.ports[port_id]
    model = state.uni_model(port_id)

    reserved = state.reserved_reason(port_id)
    if reserved is not None:
        add(Finding(Severity.INFO, "reserved", f"reserved, not configurable by this tool: {reserved}", port_id))
        return

    if model is UniModel.UNKNOWN:
        add(Finding(
            Severity.UNKNOWN, "model",
            "cannot determine whether this port carries a service; required evidence was not collected",
            port_id,
        ))
        return

    if model is UniModel.MIXED:
        add(Finding(
            Severity.ERROR, "model-mixed",
            "port has both switched-UNI bindings and platform-VLAN membership; these models are "
            "not meant to coexist on one port and the tool will refuse to modify it",
            port_id,
        ))

    if model is UniModel.TRANSPARENT:
        add(Finding(
            Severity.INFO, "t-uni",
            f"transparent UNI (I-SIDs {port.transparent_i_sids}); the tool reports but does not "
            "create these until a real example is verified",
            port_id,
        ))

    if model is UniModel.UNUSED:
        return

    # Hygiene, from the profile. Only checked on ports that carry a tenant service.
    if model in {UniModel.SWITCHED, UniModel.CVLAN}:
        for attribute, expected in profile.access_port_requirements.items():
            actual = getattr(port, attribute, None)
            if actual != expected:
                add(Finding(
                    Severity.WARNING, f"hygiene-{attribute.replace('_', '-')}",
                    f"{attribute} is {actual!r}, profile requires {expected!r}",
                    port_id,
                ))

    expected_mtu = profile.mtu
    if expected_mtu is not None and port.mtu is not None and port.mtu != expected_mtu:
        add(Finding(Severity.WARNING, "mtu", f"MTU is {port.mtu}, profile expects {expected_mtu}", port_id))

    # A switched-UNI binding's I-SID should encode its C-VID.
    for binding in port.bindings:
        if binding.c_vid is None:
            continue
        decoded = conventions.classify_isid(binding.i_sid)
        if decoded.environment is None:
            add(Finding(
                Severity.LEGACY, "binding-isid-shape",
                f"i-sid {binding.i_sid} (c-vid {binding.c_vid}) does not follow the "
                f"<prefix><vlan> convention: {decoded.note}",
                port_id,
            ))
        elif decoded.vlan_id is not None and decoded.vlan_id != binding.c_vid:
            add(Finding(
                Severity.WARNING, "binding-isid-mismatch",
                f"i-sid {binding.i_sid} encodes VLAN {decoded.vlan_id} but is bound to c-vid "
                f"{binding.c_vid}",
                port_id,
            ))
