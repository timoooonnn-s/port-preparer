"""Running-config parsing."""

from __future__ import annotations

from conftest import LAB, read
from port_preparer.parse.runconf import parse_running_config


def config():
    return parse_running_config(read(LAB, "show_running_config.txt"))


def test_device_identity_and_boot_flags():
    c = config()
    assert c.hostname == "lab-l01"
    assert c.box_type == "VSP-7254XSQ"
    assert c.software_version == "8.10.9.0"
    assert c.boot_flags == {"dvr-leaf-mode", "sshd"}
    assert c.dvr_leaf is True


def test_spbm_globals():
    c = config()
    assert c.spbm_instance == 1
    assert c.spbm_nickname == "f.30.42"
    assert c.b_vids == [4051, 4052]
    assert c.smlt_peer_system_id == "00bb.0000.0000"


def test_port_config_is_merged_across_the_two_emission_phases():
    """VOSS writes `encapsulation dot1q` in PHASE I and the rest in PHASE II, in separate
    interface blocks for the same port. Taking the first block would lose half the config."""
    port = config().port_configs["1/4"]
    assert port.encapsulation_dot1q is True     # PHASE I
    assert port.flex_uni is True                # PHASE II
    assert port.default_vlan_id == 0
    assert port.slpp_guard is True
    assert port.slpp_guard_timeout == 0
    assert port.mstp_edge_port is True
    assert port.shutdown is False


def test_one_port_carries_several_isids_tagged_and_untagged_at_once():
    """The constraint behind decision 0004: bindings are a list, not a tagging mode."""
    c = config()
    assert c.isids[2500695].port_bindings == [("1/4", 695), ("1/4", None)]
    assert c.isids[2510735].port_bindings == [("1/4", 735)]


def test_nni_port_is_distinguishable_from_an_access_port():
    port = config().port_configs["2/1"]
    assert port.isis_enabled is True
    assert port.isis_spbm_instance == 1
    assert port.name == "core-s03-w5"
    assert port.flex_uni is False


def test_mlt_lacp_key_equals_its_id():
    mlt = config().mlts[197]
    assert (mlt.smlt, mlt.lacp, mlt.lacp_key, mlt.flex_uni) == (True, True, 197, True)
    assert mlt.name == "srv-lag"


def test_bvlans_are_typed():
    c = config()
    assert c.vlans[4051].vlan_type == "spbm-bvlan"
    assert c.vlans[4052].name == "BVLAN-2"


def test_vlan_members_remove_is_applied():
    # `vlan members remove 1 1/1-1/48,2/1-2/6` leaves VLAN 1 with no members.
    assert config().vlans[1].members == []


def test_every_port_spec_in_the_capture_was_understood():
    assert config().unparsed_port_specs == []


def test_empty_input_is_safe():
    c = parse_running_config("")
    assert c.hostname is None and c.port_configs == {}
