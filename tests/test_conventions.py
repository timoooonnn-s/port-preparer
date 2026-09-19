"""Naming and numbering.

The estate is older than its own conventions, so every rule has to distinguish "does not
follow the current convention" (legacy, fine) from "wrong".
"""

from __future__ import annotations

import doctest
import ipaddress

import pytest
from port_preparer import conventions
from port_preparer.model import Environment


def test_doctests():
    assert doctest.testmod(conventions, raise_on_error=True).failed == 0


@pytest.mark.parametrize(
    ("vlan", "environment", "expected"),
    [
        (695, Environment.PROD, 2500695),
        (2200, Environment.PROD, 2502200),
        (695, Environment.NONPROD, 2700695),
        (174, Environment.SPECIAL, 2990174),
    ],
)
def test_isid_generation_is_canonical(vlan, environment, expected):
    assert conventions.isid_for_new_service(vlan, environment) == expected


def test_reserved_vlan_is_refused():
    # VLAN 31 is the reserved inter-switch trunk VLAN estate-wide.
    with pytest.raises(conventions.ConventionError):
        conventions.isid_for_new_service(31, Environment.PROD)


def test_infrastructure_isid_is_recognised_not_rejected():
    # The vIST VLAN's I-SID does not follow the <prefix><vlan> rule at all.
    decoded = conventions.classify_isid(1531100)
    assert decoded.environment is Environment.INFRA
    assert decoded.canonical is False


def test_variant_prefix_is_legacy_not_wrong():
    # 250 and 251 both mean prod; the choice was "the engineer's mood".
    canonical = conventions.classify_isid(2500695)
    variant = conventions.classify_isid(2510696)
    assert canonical.environment is variant.environment is Environment.PROD
    assert canonical.canonical is True
    assert variant.canonical is False
    assert conventions.isid_matches_vlan(2510696, 696)


def test_short_isid_is_described_not_crashed():
    decoded = conventions.classify_isid(10100)
    assert decoded.environment is None
    assert "cannot decompose" in decoded.note


@pytest.mark.parametrize(
    ("name", "network"),
    [
        ("E010041008008_30", "10.41.8.8/30"),
        ("E010035016000_21", "10.35.16.0/21"),
        ("E192168012000_22", "192.168.12.0/22"),
        ("X010054064064_27", "10.54.64.64/27"),
    ],
)
def test_vlan_name_decodes_to_its_subnet(name, network):
    decoded = conventions.decode_vlan_name(name)
    assert decoded is not None
    assert decoded.network == ipaddress.IPv4Network(network)
    assert conventions.vlan_name_is_consistent(name, network)


def test_vist_vlan_name_matches_its_peer_address():
    # 10.41.8.8/30 holds .9 and .10; show virtual-ist reports the peer as 10.41.8.10.
    decoded = conventions.decode_vlan_name("E010041008008_30")
    assert ipaddress.IPv4Address("10.41.8.10") in decoded.network


@pytest.mark.parametrize("name", ["quarantine", "Default", "BVLAN-1", "E01004100800_30", "Z999999999999_24"])
def test_non_conventional_names_decode_to_none(name):
    assert conventions.decode_vlan_name(name) is None


def test_encode_requires_an_explicit_letter():
    # The letter's meaning is unknown (open question Q3), so it is never guessed.
    assert conventions.encode_vlan_name("10.35.16.0/21", "E") == "E010035016000_21"
    with pytest.raises(conventions.ConventionError):
        conventions.encode_vlan_name("10.35.16.0/21", "EX")


def test_mlt_id_follows_4xx_for_new_lags():
    assert conventions.mlt_id_for_new_lag("1/10") == 410
    assert conventions.mlt_id_matches_port(443, "1/43")


def test_legacy_mlt_ids_are_legacy_not_errors():
    # 196-200 are the ids actually on the captured switch; they predate the 4xx rule.
    assert all(conventions.is_legacy_mlt_id(i) for i in (1, 35, 38, 196, 200))
    assert not conventions.is_legacy_mlt_id(410)


def test_channelized_port_has_no_defined_mlt_rule():
    with pytest.raises(conventions.ConventionError):
        conventions.mlt_id_for_new_lag("2/1/1")


def test_lacp_key_equals_mlt_id():
    assert conventions.lacp_key_for(197) == 197
