"""Fleet-wide service survey: harvest I-SIDs from what is configured, and find what is wrong.

This is the answer to "our I-SID names and ids are chaos, we need a valid base". The base is not
typed by hand -- it is harvested, and the valuable output is not the list of services but the
list of *inconsistencies*, which turns a feeling into something with a length.

Read-only. Every finding is graded on the same scale as the per-device audit, and the estate
being older than its own conventions still means `legacy` is not `error`.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from . import conventions
from .audit import Severity
from .fleet import FleetResult
from .model import DeviceState, Environment
from .registry import Registry, ServiceRecord


@dataclass(frozen=True)
class SurveyFinding:
    severity: Severity
    code: str
    scope: str
    message: str


@dataclass
class ServicePresence:
    """How one service appears on one switch."""

    hostname: str
    kind: str
    i_sid_name: str | None = None
    vlan_ids: set[int] = field(default_factory=set)
    port_bindings: int = 0
    mlt_bindings: int = 0
    transparent_ports: int = 0
    #: False when this device was not asked the command that would reveal terminations. An
    #: uncollected count is not a count of zero -- the same rule as decision 0008.
    terminations_known: bool = True
    locally_configured_in_isis: bool = False

    @property
    def terminations(self) -> int:
        return self.port_bindings + self.mlt_bindings + self.transparent_ports


@dataclass
class ObservedService:
    i_sid: int
    presence: dict[str, ServicePresence] = field(default_factory=dict)
    #: Remote BEBs advertising this I-SID via ISIS, from `show isis spbm i-sid all`.
    remote_endpoints: set[str] = field(default_factory=set)
    #: True when at least one device told us what the control plane sees.
    control_plane_seen: bool = False

    @property
    def hostnames(self) -> list[str]:
        return sorted(self.presence)

    @property
    def kinds(self) -> set[str]:
        return {p.kind for p in self.presence.values()}

    @property
    def names(self) -> set[str]:
        return {p.i_sid_name for p in self.presence.values() if p.i_sid_name}

    @property
    def vlan_ids(self) -> set[int]:
        out: set[int] = set()
        for presence in self.presence.values():
            out |= presence.vlan_ids
        return out

    @property
    def terminations(self) -> int:
        return sum(p.terminations for p in self.presence.values())

    @property
    def terminations_known(self) -> bool:
        return any(p.terminations_known for p in self.presence.values())

    @property
    def classification(self) -> conventions.IsidClassification:
        return conventions.classify_isid(self.i_sid)


@dataclass
class ServiceSurvey:
    services: dict[int, ObservedService] = field(default_factory=dict)
    #: vid -> {hostname: vlan name}
    vlan_names: dict[int, dict[str, str]] = field(default_factory=dict)
    #: vid -> set of I-SIDs it is mapped to anywhere in the fleet
    vlan_to_isids: dict[int, set[int]] = field(default_factory=dict)
    findings: list[SurveyFinding] = field(default_factory=list)
    #: Collected during checking, then summarised into one finding each rather than hundreds.
    _orphan_unknown: list[int] = field(default_factory=list)
    _terminations_unknown: list[int] = field(default_factory=list)
    as_of: str = ""
    coverage: str = ""
    unreachable: list[str] = field(default_factory=list)

    @property
    def partial(self) -> bool:
        """True when some devices were not reached, which softens 'this exists nowhere else'."""
        return bool(self.unreachable)

    def counts(self) -> dict[str, int]:
        out: dict[str, int] = {}
        for finding in self.findings:
            out[finding.severity.value] = out.get(finding.severity.value, 0) + 1
        return out

    def sorted_findings(self) -> list[SurveyFinding]:
        return sorted(self.findings, key=lambda f: (f.severity.rank, f.scope, f.code))


def survey(fleet: FleetResult, *, registry: Registry | None = None) -> ServiceSurvey:
    result = ServiceSurvey(
        as_of=fleet.as_of,
        coverage=fleet.coverage(),
        unreachable=sorted(r.hostname for r in fleet.failed),
    )
    for device in fleet.reached:
        assert device.state is not None
        _absorb(result, device.hostname, device.state)

    _check_services(result)
    _check_vlans(result)
    _summarise_unknowns(result)
    if registry is not None:
        _check_registry(result, registry)
    return result


def _summarise_unknowns(survey_result: ServiceSurvey) -> None:
    """Roll the "we could not tell" cases into one finding each.

    Emitting one per service would bury the real findings under hundreds of rows, which is the
    surest way to get a compliance tool ignored.
    """
    if survey_result._orphan_unknown:
        count = len(survey_result._orphan_unknown)
        survey_result.findings.append(SurveyFinding(
            Severity.UNKNOWN, "orphan-check-unavailable", "fleet",
            f"{count} service(s) were seen on only one crawled switch, but "
            "`show isis spbm i-sid all` was not collected, so whether they have a remote endpoint "
            f"is unknown. Collect that command to settle it. First: {survey_result._orphan_unknown[0]}",
        ))
    if survey_result._terminations_unknown:
        count = len(survey_result._terminations_unknown)
        survey_result.findings.append(SurveyFinding(
            Severity.UNKNOWN, "terminations-unknown", "fleet",
            f"{count} service(s) have no ports or MLTs recorded, but the commands that would "
            "reveal them were not collected on the devices carrying them, so this is not the same "
            f"as having none. First: {survey_result._terminations_unknown[0]}",
        ))


def _absorb(survey_result: ServiceSurvey, hostname: str, state: DeviceState) -> None:
    knows_bindings = "i-sid-bindings" in state.evidence
    knows_members = "vlan-members" in state.evidence

    for i_sid, entry in state.spbm_isids.items():
        observed = survey_result.services.setdefault(i_sid, ObservedService(i_sid=i_sid))
        observed.control_plane_seen = True
        observed.remote_endpoints |= set(entry.advertised_by)
        if entry.locally_configured:
            presence = observed.presence.setdefault(
                hostname, ServicePresence(hostname=hostname, kind="unknown", terminations_known=False)
            )
            presence.locally_configured_in_isis = True

    for i_sid, isid in state.isids.items():
        observed = survey_result.services.setdefault(i_sid, ObservedService(i_sid=i_sid))
        previous = observed.presence.get(hostname)
        presence = ServicePresence(
            hostname=hostname,
            kind=isid.kind,
            i_sid_name=isid.name,
            port_bindings=len(isid.port_bindings),
            mlt_bindings=len(isid.mlt_bindings),
            transparent_ports=len(isid.transparent_ports),
            terminations_known=knows_bindings,
            locally_configured_in_isis=bool(previous and previous.locally_configured_in_isis),
        )
        presence.vlan_ids = {c_vid for _, c_vid in isid.port_bindings if c_vid is not None}
        presence.vlan_ids |= {c_vid for _, c_vid in isid.mlt_bindings if c_vid is not None}
        observed.presence[hostname] = presence

    for vid, vlan in state.vlans.items():
        if vlan.is_bvlan or vid in conventions.RESERVED_VLAN_IDS:
            continue
        if vlan.name:
            survey_result.vlan_names.setdefault(vid, {})[hostname] = vlan.name
        if vlan.i_sid is not None:
            survey_result.vlan_to_isids.setdefault(vid, set()).add(vlan.i_sid)
            observed = survey_result.services.setdefault(
                vlan.i_sid, ObservedService(i_sid=vlan.i_sid)
            )
            presence = observed.presence.setdefault(
                hostname, ServicePresence(hostname=hostname, kind="cvlan")
            )
            if presence.kind == "unknown":
                presence.kind = "cvlan"
            presence.terminations_known = presence.terminations_known and knows_members
            presence.vlan_ids.add(vid)
            presence.i_sid_name = presence.i_sid_name or vlan.i_sid_name
            presence.port_bindings = presence.port_bindings or len(vlan.static_members)


def _check_services(survey_result: ServiceSurvey) -> None:
    add = survey_result.findings.append

    for i_sid, service in sorted(survey_result.services.items()):
        scope = f"i-sid {i_sid}"
        decoded = service.classification

        # -- numbering ------------------------------------------------------------
        if decoded.environment is Environment.INFRA:
            add(SurveyFinding(
                Severity.INFO, "isid-infra", scope,
                f"infrastructure I-SID ({decoded.note}); never generated by this tool",
            ))
        elif decoded.environment is None:
            add(SurveyFinding(
                Severity.LEGACY if decoded.vlan_id is None else Severity.WARNING,
                "isid-prefix", scope,
                f"does not follow the <prefix><vlan> convention: {decoded.note}",
            ))
        else:
            expected = service.vlan_ids
            if not decoded.canonical:
                add(SurveyFinding(Severity.LEGACY, "isid-prefix-variant", scope, decoded.note or ""))
            if expected and decoded.vlan_id not in expected:
                add(SurveyFinding(
                    Severity.WARNING, "isid-vlan-mismatch", scope,
                    f"encodes VLAN {decoded.vlan_id} but is used with VLAN/C-VID "
                    f"{sorted(expected)}",
                ))

        # -- naming ----------------------------------------------------------------
        if len(service.names) > 1:
            add(SurveyFinding(
                Severity.WARNING, "isid-name-conflict", scope,
                "one service is labelled differently on different switches: "
                + ", ".join(
                    f"{host}={presence.i_sid_name!r}"
                    for host, presence in sorted(service.presence.items())
                    if presence.i_sid_name
                ),
            ))
        elif not service.names:
            add(SurveyFinding(
                Severity.INFO, "isid-unnamed", scope,
                f"no I-SID name on any of {len(service.presence)} switch(es)",
            ))

        # -- one service, two UNI models ------------------------------------------
        if len(service.kinds) > 1:
            add(SurveyFinding(
                Severity.WARNING, "isid-model-split", scope,
                "the same service uses different UNI models on different switches: "
                + ", ".join(
                    f"{host}={presence.kind}" for host, presence in sorted(service.presence.items())
                ),
            ))

        # -- locally significant C-VIDs -------------------------------------------
        if len(service.vlan_ids) > 1:
            severity = (
                Severity.INFO if service.kinds == {"elan"} else Severity.WARNING
            )
            add(SurveyFinding(
                severity, "isid-multiple-vlans", scope,
                f"used with VLAN/C-VID {sorted(service.vlan_ids)}"
                + (
                    " -- legitimate for switched UNI, where C-VIDs are locally significant"
                    if severity is Severity.INFO
                    else " -- with a platform VLAN this means the service means different things "
                    "in different places"
                ),
            ))

        # -- orphans ---------------------------------------------------------------
        # The authoritative test is the ISIS control plane, not how many switches we crawled:
        # `show isis spbm i-sid all` distinguishes locally configured from discovered-from-a-
        # remote-BEB, so a single switch can tell us whether a service has a far end at all.
        if decoded.environment is not Environment.INFRA and service.control_plane_seen:
            configured_here = any(p.locally_configured_in_isis for p in service.presence.values())
            if configured_here and not service.remote_endpoints:
                add(SurveyFinding(
                    Severity.WARNING, "isid-orphan", scope,
                    "configured locally but no remote BEB advertises it in ISIS, so this L2 VSN "
                    "has no far end and carries nothing between switches",
                ))
        elif decoded.environment is not Environment.INFRA and len(service.presence) == 1:
            survey_result._orphan_unknown.append(i_sid)

        # An uncollected termination count is not a count of zero (decision 0008).
        if service.terminations == 0 and service.terminations_known:
            add(SurveyFinding(
                Severity.WARNING, "isid-no-terminations", scope,
                "exists but has no port or MLT bound to it on any switch reached",
            ))
        elif service.terminations == 0:
            survey_result._terminations_unknown.append(i_sid)


def _check_vlans(survey_result: ServiceSurvey) -> None:
    add = survey_result.findings.append

    for vid, isids in sorted(survey_result.vlan_to_isids.items()):
        if len(isids) > 1:
            add(SurveyFinding(
                Severity.WARNING, "vlan-multiple-isids", f"vlan {vid}", 
                f"mapped to more than one I-SID across the fleet: {sorted(isids)}. One of these "
                "is almost certainly wrong.",
            ))

    for vid, names in sorted(survey_result.vlan_names.items()):
        distinct = set(names.values())
        scope = f"vlan {vid}"
        if len(distinct) > 1:
            add(SurveyFinding(
                Severity.WARNING, "vlan-name-conflict", scope,
                "named differently on different switches: "
                + ", ".join(f"{host}={name!r}" for host, name in sorted(names.items())),
            ))
            continue
        name = next(iter(distinct))
        if conventions.decode_vlan_name(name) is None:
            add(SurveyFinding(
                Severity.LEGACY, "vlan-name", scope,
                f"named {name!r}, which does not follow the "
                "<LETTER><12-digit network>_<prefixlen> convention",
            ))


def _check_registry(survey_result: ServiceSurvey, registry: Registry) -> None:
    add = survey_result.findings.append
    known = {record.i_sid for record in registry.services()}

    for i_sid in sorted(survey_result.services):
        if i_sid not in known:
            add(SurveyFinding(
                Severity.INFO, "not-in-registry", f"i-sid {i_sid}",
                "configured on the network but not in the registry; --harvest would import it",
            ))

    configured = set(survey_result.services)
    for record in registry.services():
        if record.i_sid not in configured and record.status == "deployed":
            add(SurveyFinding(
                Severity.WARNING, "registry-only", f"i-sid {record.i_sid}",
                f"the registry says this is deployed, but it was not found on any device "
                f"reached. Registry entry: {record.name or 'unnamed'}",
            ))


def harvest(
    survey_result: ServiceSurvey, registry: Registry, *, dry_run: bool = False
) -> tuple[list[ServiceRecord], list[int]]:
    """Import observed services into the registry as `harvested` entries.

    Idempotent: an I-SID already in the registry is left alone, never overwritten with what the
    network happens to say today. Returns (created, skipped).
    """
    created: list[ServiceRecord] = []
    skipped: list[int] = []

    for i_sid, service in sorted(survey_result.services.items()):
        if registry.get_service(i_sid) is not None:
            skipped.append(i_sid)
            continue
        decoded = service.classification
        vlan_ids = sorted(service.vlan_ids)
        record = ServiceRecord(
            i_sid=i_sid,
            vlan_id=vlan_ids[0] if len(vlan_ids) == 1 else decoded.vlan_id,
            environment=decoded.environment.value if decoded.environment else None,
            name=sorted(service.names)[0] if service.names else None,
            status="harvested",
            snapshot={
                "as_of": survey_result.as_of,
                "coverage": survey_result.coverage,
                "switches": service.hostnames,
                "kinds": sorted(service.kinds),
                "vlan_ids": vlan_ids,
                "terminations": service.terminations,
            },
            notes=[
                "Imported from what was configured on the network. The purpose, owner and "
                "application are not known and must be filled in by a human; the snapshot is a "
                "point-in-time observation, not authority."
            ],
        )
        if not dry_run:
            registry.allocate_service(record)
        created.append(record)

    return created, skipped
