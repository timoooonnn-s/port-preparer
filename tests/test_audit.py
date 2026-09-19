"""The audit: what it flags, and what it deliberately does not."""

from __future__ import annotations

from port_preparer.audit import Severity, audit
from port_preparer.model import Vlan
from port_preparer.profiles import ProfileSet


def run(state_and_report, **kwargs):
    state, report = state_and_report
    return audit(state, report, **kwargs)


def codes(result, severity=None):
    return {f.code for f in result.findings if severity is None or f.severity is severity}


def test_mixed_model_port_is_an_error(lab_state):
    result = run(lab_state, site_category="dc")
    assert "model-mixed" in codes(result, Severity.ERROR)


def test_legacy_conventions_are_not_errors(lab_state):
    """The estate predates its own rules. Reporting history as breakage would get the tool
    ignored, which is the most likely way this project fails."""
    result = run(lab_state, site_category="dc")
    legacy = codes(result, Severity.LEGACY)
    assert "vlan-name" in legacy or "binding-isid-shape" in legacy
    assert not any(f.severity is Severity.ERROR and f.code.startswith("vlan-name") for f in result.findings)


def test_variant_isid_prefix_is_legacy_rather_than_a_mismatch(lab_state):
    state, report = lab_state
    # 251 is the variant prod prefix: 2510696 still encodes VLAN 696 correctly.
    state.vlans[696] = Vlan(vid=696, name="E010034064000_24", i_sid=2510696)
    result = audit(state, report, site_category="dc")
    assert "isid-prefix-variant" in codes(result, Severity.LEGACY)
    assert "isid-vlan-mismatch" not in codes(result)


def test_isid_not_encoding_its_vlan_is_a_warning(lab_state):
    state, report = lab_state
    # I-SID 2500699 encodes VLAN 699, but it is mapped to VLAN 695.
    state.vlans[695] = Vlan(vid=695, name="E010035016000_21", i_sid=2500699)
    result = audit(state, report, site_category="dc")
    assert "isid-vlan-mismatch" in codes(result, Severity.WARNING)


def test_hygiene_is_checked_only_on_service_carrying_ports(lab_state):
    result = run(lab_state, site_category="dc")
    hygiene = [f for f in result.findings if f.code.startswith("hygiene-")]
    assert hygiene
    # 1/4 is the known-good port from the captured running-config: it must be clean.
    assert not [f for f in hygiene if f.port_id == "1/4"]
    # Reserved ports are never hygiene-checked.
    assert not [f for f in hygiene if f.port_id in {"2/1", "1/47", "1/48"}]


def test_reserved_ports_are_reported_as_info_and_skipped(lab_state):
    result = run(lab_state, site_category="dc")
    reserved = [f for f in result.findings if f.code == "reserved"]
    assert {f.port_id for f in reserved} >= {"2/1", "1/47", "1/48"}
    assert all(f.severity is Severity.INFO for f in reserved)


def test_dvr_leaf_is_surfaced_because_nobody_mentioned_it(lab_state):
    result = run(lab_state, site_category="dc")
    assert "dvr-leaf" in codes(result, Severity.INFO)


def test_vist_pair_is_surfaced_so_dual_homing_is_not_forgotten(prod_state):
    result = run(prod_state, site_category="dc")
    assert "vist" in codes(result, Severity.INFO)


def test_missing_evidence_is_its_own_severity(prod_state):
    result = run(prod_state, site_category="dc")
    assert "missing-evidence" in codes(result, Severity.UNKNOWN)
    assert "model" in codes(result, Severity.UNKNOWN)


def test_legacy_mlt_ids_do_not_fail_the_audit(prod_state):
    result = run(prod_state, site_category="dc")
    assert "mlt-id" in codes(result, Severity.LEGACY)
    assert "mlt-id" not in codes(result, Severity.ERROR)


def test_nni_mlt_is_recognised_and_not_convention_checked(prod_state):
    result = run(prod_state, site_category="dc")
    assert "mlt-nni" in codes(result, Severity.INFO)
    assert not [f for f in result.findings if f.code == "lacp-key" and "MLT 1 " in f.message]


def test_ok_ignores_legacy_and_info(lab_state):
    state, report = lab_state
    result = audit(state, report, site_category="dc")
    assert result.ok is False
    result.findings = [f for f in result.findings if f.severity in {Severity.LEGACY, Severity.INFO}]
    assert result.ok is True


def test_management_role_is_matched_from_the_hostname(lab_state):
    state, report = lab_state
    state.hostname = "m01-core"
    result = audit(state, report, site_category="dc")
    assert "role" in codes(result, Severity.INFO)
    assert "roles.management-switch" in result.profile.layers


def test_profile_layers_are_recorded(lab_state):
    result = run(lab_state, site_category="dc", scenario="dc-server-access")
    assert result.profile.layers == ["global", "site_categories.dc", "scenarios.dc-server-access"]


def test_unknown_scenario_is_rejected(lab_state):
    state, report = lab_state
    try:
        audit(state, report, scenario="does-not-exist")
    except Exception as exc:
        assert "does-not-exist" in str(exc)
    else:
        raise AssertionError("an unknown scenario should not be silently accepted")


def test_default_profile_loads():
    profiles = ProfileSet.load()
    assert profiles.scenario_names() == ["dc-server-access", "management", "non-dc-access"]
