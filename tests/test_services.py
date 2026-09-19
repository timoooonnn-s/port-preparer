"""The fleet-wide service survey.

The synthetic fleet fixture has six deliberate inconsistencies; each is asserted here. Just as
important are the things the survey must NOT say, because a tool that reports the whole estate as
broken gets ignored.
"""

from __future__ import annotations

from port_preparer.audit import Severity
from port_preparer.registry import ServiceRecord
from port_preparer.services import harvest, survey


def codes(result, severity=None):
    return {f.code for f in result.findings if severity is None or f.severity is severity}


def find(result, code):
    return [f for f in result.findings if f.code == code]


# --- the six deliberate inconsistencies -------------------------------------------

def test_one_service_labelled_differently_on_two_switches(fleet_survey):
    findings = find(fleet_survey, "isid-name-conflict")
    assert {f.scope for f in findings} == {"i-sid 2500695", "i-sid 2500696"}
    assert "payroll-prod" in findings[0].message and "payroll-production" in findings[0].message


def test_one_service_using_both_uni_models(fleet_survey):
    findings = find(fleet_survey, "isid-model-split")
    assert [f.scope for f in findings] == ["i-sid 2500696"]
    assert "elan" in findings[0].message and "cvlan" in findings[0].message


def test_orphan_is_proven_from_the_isis_control_plane(fleet_survey):
    """Not "I only saw it on one switch I crawled" -- `show isis spbm i-sid all` distinguishes
    locally configured from discovered-from-a-remote-BEB, so one switch can settle it."""
    findings = find(fleet_survey, "isid-orphan")
    assert [f.scope for f in findings] == ["i-sid 2500699"]
    assert "no remote BEB advertises it" in findings[0].message


def test_isid_not_encoding_the_vlan_it_is_bound_to(fleet_survey):
    findings = find(fleet_survey, "isid-vlan-mismatch")
    assert [f.scope for f in findings] == ["i-sid 2519999"]
    assert "9999" in findings[0].message and "700" in findings[0].message


def test_vlan_named_differently_on_two_switches(fleet_survey):
    assert [f.scope for f in find(fleet_survey, "vlan-name-conflict")] == ["vlan 800"]


def test_one_vlan_mapped_to_two_isids(fleet_survey):
    findings = find(fleet_survey, "vlan-multiple-isids")
    assert [f.scope for f in findings] == ["vlan 801"]
    assert "2500801" in findings[0].message and "2700801" in findings[0].message


# --- what it must not say ----------------------------------------------------------

def test_legacy_prefix_variant_is_legacy_not_a_warning(fleet_survey):
    findings = find(fleet_survey, "isid-prefix-variant")
    assert findings and all(f.severity is Severity.LEGACY for f in findings)


def test_services_with_a_remote_endpoint_are_not_called_orphans(fleet_survey):
    scopes = {f.scope for f in find(fleet_survey, "isid-orphan")}
    assert "i-sid 2500695" not in scopes
    assert "i-sid 2519999" not in scopes


def test_uncollected_termination_counts_are_not_reported_as_zero(prod_state):
    """Regression for the same class of bug as decision 0008, reintroduced once in the survey.

    The production capture has no `show vlan members` or `show i-sid`, so nothing is known about
    terminations. That must not be reported as "has no ports bound".
    """
    from port_preparer.fleet import FleetResult, DeviceResult

    state, report = prod_state
    fleet = FleetResult(started_at="t0", finished_at="t0")
    fleet.results["sw-prod"] = DeviceResult(hostname="sw-prod", state=state, report=report)
    result = survey(fleet)
    assert "isid-no-terminations" not in codes(result)


def test_unknowns_are_summarised_into_one_finding_each(fleet_survey):
    """Emitting one per service would bury the real findings under hundreds of rows."""
    unavailable = find(fleet_survey, "orphan-check-unavailable")
    assert len(unavailable) <= 1
    if unavailable:
        assert unavailable[0].severity is Severity.UNKNOWN
        assert unavailable[0].scope == "fleet"


def test_the_real_findings_are_not_drowned(fleet_survey):
    counts = fleet_survey.counts()
    assert counts.get("warning", 0) <= 10, f"too noisy to be usable: {counts}"


# --- structure ---------------------------------------------------------------------

def test_survey_records_coverage_and_a_timestamp(fleet_survey):
    assert fleet_survey.coverage == "2/2 device(s) reached"
    assert fleet_survey.as_of
    assert fleet_survey.partial is False


def test_remote_endpoints_are_collected_per_service(fleet_survey):
    assert fleet_survey.services[2500695].remote_endpoints == {"sw-syn-a1", "sw-syn-a2"}
    assert fleet_survey.services[2500699].remote_endpoints == set()


def test_locally_significant_cvids_are_informational_for_switched_uni(fleet_survey):
    findings = find(fleet_survey, "isid-multiple-vlans")
    for finding in findings:
        service = fleet_survey.services[int(finding.scope.split()[-1])]
        expected = Severity.INFO if service.kinds == {"elan"} else Severity.WARNING
        assert finding.severity is expected


# --- harvesting --------------------------------------------------------------------

def test_harvest_imports_every_observed_service(fleet_survey, registry):
    created, skipped = harvest(fleet_survey, registry)
    assert {r.i_sid for r in created} == set(fleet_survey.services)
    assert skipped == []
    assert {s.i_sid for s in registry.services()} == set(fleet_survey.services)


def test_harvested_entries_admit_they_lack_identity(fleet_survey, registry):
    harvest(fleet_survey, registry)
    record = registry.get_service(2500695)
    assert record.status == "harvested"
    assert record.identity_known is False
    assert record.snapshot["switches"] == ["sw-syn-a1", "sw-syn-a2"]
    assert record.snapshot["as_of"] == fleet_survey.as_of
    assert any("not authority" in note for note in record.notes)


def test_harvest_is_idempotent_and_never_overwrites(fleet_survey, registry):
    registry.allocate_service(
        ServiceRecord(i_sid=2500695, name="curated-by-a-human", owner="netops", status="deployed")
    )
    created, skipped = harvest(fleet_survey, registry)
    assert 2500695 in skipped
    assert 2500695 not in {r.i_sid for r in created}
    assert registry.get_service(2500695).name == "curated-by-a-human"


def test_dry_run_harvest_writes_nothing(fleet_survey, registry):
    created, _ = harvest(fleet_survey, registry, dry_run=True)
    assert created
    assert registry.services() == []


def test_survey_flags_services_missing_from_the_registry(fleet_survey, registry):
    from port_preparer.fleet import collect_fleet
    from port_preparer.transport import MockTransport
    from conftest import FLEET

    fleet = collect_fleet(
        ["sw-syn-a1", "sw-syn-a2"], lambda h: MockTransport(FLEET / h, host=h), workers=2
    )
    result = survey(fleet, registry=registry)
    assert "not-in-registry" in codes(result, Severity.INFO)


def test_survey_flags_a_registry_entry_that_is_deployed_but_absent(registry):
    from port_preparer.fleet import collect_fleet
    from port_preparer.transport import MockTransport
    from conftest import FLEET

    registry.allocate_service(ServiceRecord(i_sid=2509999, name="ghost", status="deployed"))
    fleet = collect_fleet(
        ["sw-syn-a1", "sw-syn-a2"], lambda h: MockTransport(FLEET / h, host=h), workers=2
    )
    result = survey(fleet, registry=registry)
    findings = find(result, "registry-only")
    assert [f.scope for f in findings] == ["i-sid 2509999"]
    assert findings[0].severity is Severity.WARNING


def test_a_reserved_registry_entry_is_not_reported_as_missing(registry):
    from port_preparer.fleet import collect_fleet
    from port_preparer.transport import MockTransport
    from conftest import FLEET

    registry.allocate_service(ServiceRecord(i_sid=2509999, name="planned", status="reserved"))
    fleet = collect_fleet(
        ["sw-syn-a1", "sw-syn-a2"], lambda h: MockTransport(FLEET / h, host=h), workers=2
    )
    assert "registry-only" not in codes(survey(fleet, registry=registry))
