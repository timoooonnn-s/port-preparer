"""Parsers against captured output.

The standing rule: every parser must consume every row of every fixture with nothing skipped.
A skipped line is a silently under-reported device, which is how an audit ends up lying.
"""

from __future__ import annotations

import pytest
from conftest import LAB, NINE_X, PROD, read
from port_preparer.parse import voss

_CASES = [
    (voss.parse_vlan_basic, LAB, "show_vlan_basic.txt", 5),
    (voss.parse_vlan_basic, PROD, "show_vlan_basic.txt", 39),
    (voss.parse_vlan_i_sid, LAB, "show_vlan_i_sid.txt", 5),
    (voss.parse_vlan_i_sid, PROD, "show_vlan_i_sid.txt", 39),
    (voss.parse_vlan_members, LAB, "show_vlan_members.txt", 5),
    (voss.parse_vlan_members, NINE_X, "show_vlan_members.txt", 3),
    (voss.parse_i_sid, LAB, "show_i_sid.txt", 4),
    (voss.parse_port_i_sid, LAB, "show_interfaces_gigabitethernet_i_sid.txt", 3),
    (voss.parse_port_interface, PROD, "show_interfaces_gigabitethernet_interface.txt", 54),
    (voss.parse_port_interface, LAB, "show_interfaces_gigabitethernet.txt", 5),
    (voss.parse_port_name, LAB, "show_interfaces_gigabitethernet.txt", 5),
    (voss.parse_port_config, LAB, "show_interfaces_gigabitethernet.txt", 2),
    (voss.parse_mlt, LAB, "show_mlt.txt", 3),
    (voss.parse_mlt, PROD, "show_mlt.txt", 8),
    (voss.parse_virtual_ist, PROD, "show_virtual_ist.txt", 1),
    (voss.parse_dvr_interfaces, LAB, "show_dvr_interfaces.txt", 3),
    (voss.parse_lldp_neighbor_summary, PROD, "show_lldp_neighbor_summary.txt", 15),
]


@pytest.mark.parametrize(("parser", "directory", "filename", "expected"), _CASES)
def test_parses_every_row_with_nothing_skipped(parser, directory, filename, expected):
    result = parser(read(directory, filename))
    assert result.skipped == [], f"{parser.__name__} skipped: {result.skipped}"
    assert len(result.rows) == expected


def test_parsers_return_empty_on_empty_input():
    for parser, _, _, _ in _CASES:
        result = parser("")
        assert result.rows == [] and result.skipped == []


def test_mlt_wrapped_vlan_list_is_not_dropped():
    """Regression: MLT 2's VLAN IDS column wraps onto a continuation line holding `2600 2601`.

    The continuation starts at column 0 and contains only digits, so it cannot be recognised
    by indentation. Dropping it under-reported the MLT's VLANs by two.
    """
    rows = {row["mlt_id"]: row for row in voss.parse_mlt(read(LAB, "show_mlt.txt")).rows}
    assert 2600 in rows[2]["vlan_ids"]
    assert 2601 in rows[2]["vlan_ids"]
    assert len(rows[2]["vlan_ids"]) == 14


def test_vlan_members_wrapped_rows_are_rejoined_without_a_separator():
    """Regression: 9.x wraps member lists mid-token, so the halves must be concatenated."""
    rows = {row["vid"]: row for row in voss.parse_vlan_members(read(NINE_X, "show_vlan_members.txt")).rows}
    assert rows[1]["port_members"] == "1/1-1/16,1/17/1-1/18/4,2/1"


def test_i_sid_type_column_distinguishes_the_two_uni_models():
    rows = {row["i_sid"]: row for row in voss.parse_i_sid(read(LAB, "show_i_sid.txt")).rows}
    assert rows[10100]["type"] == "ELAN"        # switched UNI
    assert rows[2502201]["type"] == "CVLAN"     # platform VLAN + i-sid


def test_i_sid_binding_notation():
    rows = {row["i_sid"]: row for row in voss.parse_i_sid(read(LAB, "show_i_sid.txt")).rows}
    assert rows[10100]["port_bindings"] == [("1/10", 100), ("1/11", 100)]
    assert rows[10100]["mlt_bindings"] == [("2", 100)]
    assert rows[10200]["port_bindings"] == []


def test_untagged_binding_notation_decodes_to_none():
    assert voss.parse_binding_list("u:1/4") == [("1/4", None)]
    assert voss.parse_binding_list("c695:1/4,u:1/4") == [("1/4", 695), ("1/4", None)]
    assert voss.parse_binding_list("-") == []


def test_port_name_section_handles_a_port_with_no_name():
    # The NAME field is absent on ports that have none, so the row is one column shorter.
    rows = voss.parse_port_name(
        "PORT                                              OPERATE\n"
        "NUM      NAME                 DESCRIPTION         LINKTRAP  STATUS  DUPLEX SPEED\n"
        "-----------------------------------------------------------------------\n"
        "1/1      to-core-01           1000BaseTX          true      up      full   1000\n"
        "1/2      1000BaseTX           true      down    down   0\n"
    )
    assert rows.skipped == []
    assert rows.rows[0]["name"] == "to-core-01"
    assert rows.rows[1]["name"] is None


def test_lldp_columns_survive_fields_containing_spaces():
    rows = {r["port_id"]: r for r in voss.parse_lldp_neighbor_summary(read(PROD, "show_lldp_neighbor_summary.txt")).rows}
    assert rows["1/1"]["sysname"] == "sw-aa-s03-wu"
    assert rows["1/1"]["sysdescr"] == "VSP-7400-48Y-8C (9.3.1.0)"
    # A server with no LLDP sysname, whose remote port contains a space.
    assert rows["1/7"]["sysname"] is None
    assert rows["1/7"]["remote_port"] == "Embedded ALOM, Po~"


def test_prod_capture_confirms_the_mlt_id_convention_conflict():
    """The stated rule is 4xx-encodes-the-port; the captured switch does not follow it.

    Pinned as a test so the conflict cannot be quietly forgotten -- it is open question Q1.
    """
    rows = {row["mlt_id"]: row for row in voss.parse_mlt(read(PROD, "show_mlt.txt")).rows}
    assert rows[196]["ports"] == "1/10"       # the 4xx rule would give MLT 410
    assert rows[196]["name"] == "f110"        # the port is encoded in the name instead
