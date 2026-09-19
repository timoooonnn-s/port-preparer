"""Discovery: assembling parsed output into a device state."""

from __future__ import annotations

from conftest import LAB, PROD, PROD_PARTIAL
from port_preparer.collect import collect
from port_preparer.discover import discover
from port_preparer.model import Binding, UniModel
from port_preparer.transport import MockTransport


def test_lab_device_identity(lab_state):
    state, _ = lab_state
    assert state.hostname == "lab-l01"
    assert state.dvr_leaf is True
    assert state.bvlans == [4051, 4052]


def test_uni_model_is_detected_per_port(lab_state):
    state, _ = lab_state
    assert state.uni_model("1/4") is UniModel.SWITCHED
    assert state.uni_model("1/47") is UniModel.CVLAN
    assert state.uni_model("2/1") is UniModel.NNI


def test_a_port_with_both_models_is_flagged_mixed_not_guessed(lab_state):
    state, _ = lab_state
    # 1/1 has switched-UNI bindings via its MLT and platform-VLAN membership.
    assert state.uni_model("1/1") is UniModel.MIXED


def test_bindings_are_a_list_including_tagged_and_untagged_on_one_isid(lab_state):
    state, _ = lab_state
    bindings = state.ports["1/4"].bindings
    assert Binding(i_sid=2500695, c_vid=695) in bindings
    assert Binding(i_sid=2500695, c_vid=None) in bindings
    assert Binding(i_sid=2510735, c_vid=735) in bindings


def test_mlt_bindings_are_projected_onto_member_ports(lab_state):
    state, _ = lab_state
    # `show i-sid` binds i-sid 10100 to MLT 2, whose members are 1/1 and 1/2.
    assert any(b.i_sid == 10100 for b in state.ports["1/1"].bindings)
    assert any(b.i_sid == 10100 for b in state.ports["1/2"].bindings)


def test_reserved_objects_are_refused(lab_state):
    state, _ = lab_state
    assert "vIST VLAN" in (state.reserved_reason("1/47") or "")
    assert state.reserved_reason("2/1") == "ISIS/NNI fabric link"
    assert state.reserved_reason("1/4") is None


def test_prod_vist_pair_is_detected(prod_state):
    state, _ = prod_state
    assert state.vist_peer_ip == "10.41.8.10"
    assert state.vist_vlan == 31


def test_nni_mlt_members_are_reserved(prod_state):
    state, _ = prod_state
    # MLT 1 carries only B-VLANs 4051/4052: it is the ISIS link to the vIST peer.
    assert "B-VLANs" in (state.reserved_reason("1/8") or "")
    assert "B-VLANs" in (state.reserved_reason("1/16") or "")


def test_missing_evidence_reports_unknown_not_unused(prod_state):
    """A tool that says "this port is free" because it failed to ask is worse than one that
    admits it does not know."""
    state, _ = prod_state
    assert state.missing_evidence == {"vlan-members", "i-sid-bindings"}
    assert state.uni_model("1/3") is UniModel.UNKNOWN
    assert all(state.uni_model(p) is UniModel.UNKNOWN for p in state.ports)


def test_full_evidence_permits_an_unused_verdict(lab_state):
    state, _ = lab_state
    assert state.missing_evidence == set()


def test_prod_capture_has_every_port_and_mlt(prod_state):
    state, _ = prod_state
    assert len(state.ports) == 54
    assert set(state.mlts) == {1, 35, 38, 196, 197, 198, 199, 200}
    assert state.mlts[196].ports == ["1/10"]
    assert state.mlts[35].ports == ["1/1", "1/2", "1/23", "1/24"]


def test_neighbours_are_attached_to_ports(prod_state):
    state, _ = prod_state
    assert state.neighbors["1/10"].sysdescr == "HPE ProLiant DL580 Gen10"
    assert state.neighbors["1/8"].sysname == "sw-aa-s01-p2"


def test_drift_between_sources_is_recorded_not_reconciled(lab_state):
    _, report = lab_state
    # The lab capture's per-port i-sid table does not list 1/4's configured bindings.
    assert any("1/4" in message for message in report.binding_disagreements)


def test_drift_is_reported_once_per_port_and_isid(lab_state):
    _, report = lab_state
    assert len(report.binding_disagreements) == len(set(report.binding_disagreements))


def test_a_partial_capture_still_produces_a_state():
    state, report = discover(collect(MockTransport(PROD_PARTIAL)))
    assert state.collection_errors           # it says what it could not get
    assert state.vist_vlan == 31             # and still uses what it could
    assert report.skipped_lines == {}
