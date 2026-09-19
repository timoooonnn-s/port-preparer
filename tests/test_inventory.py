"""Device inventory from CSV. An inventory that must be complete before the tool runs is an
inventory that never gets used, so absent fields are reported, not fatal."""

from __future__ import annotations

import pytest
from port_preparer.inventory import UNRELATED, Inventory, InventoryError, Location

MESSY = """﻿Hostname;Site;Gebaeude;Raum;Reihe;Rack;HE;Management IP;Model;SMLT Peer;Site Type;Role
sw-aa-s01-p1;aa;B1;2;R3;B12;20;10.0.0.30;VSP-7254XSQ;sw-aa-s01-p2;dc;dc-access
sw-aa-s01-p2;aa;B1;2;R3;B12;22;10.0.0.31;VSP-7254XSQ;sw-aa-s01-p1;dc;dc-access
sw-aa-s03-wu;aa;B1;2;R1;A01;40;10.0.0.70;VSP-7400-48Y-8C;;dc;dc-spine
m01-aa;aa;B1;2;R3;B12;;10.0.0.200;;;dc;
sw-bb-s01-p1;bb;;;;;;10.1.0.30;;;branch;branch-access
"""


@pytest.fixture
def inventory(tmp_path):
    path = tmp_path / "devices.csv"
    path.write_text(MESSY, encoding="utf-8")
    return Inventory.load_csv(path)


def test_loads_semicolons_german_headers_and_a_bom(inventory):
    assert len(inventory) == 5
    device = inventory.get("sw-aa-s01-p1")
    assert device.location.rack == "B12"
    assert device.location.rack_unit == 20
    assert device.mgmt_address == "10.0.0.30"
    assert device.platform == "VSP-7254XSQ"
    assert device.vist_peer == "sw-aa-s01-p2"
    assert device.site_category == "dc"


def test_hostname_lookup_is_case_insensitive(inventory):
    assert inventory.get("SW-AA-S01-P1") is not None


def test_target_prefers_the_management_address(inventory):
    assert inventory.get("sw-aa-s01-p1").target == "10.0.0.30"


def test_distance_ladder(inventory):
    a1 = inventory.get("sw-aa-s01-p1").location
    a2 = inventory.get("sw-aa-s01-p2").location
    spine = inventory.get("sw-aa-s03-wu").location
    assert a1.distance_to(a2) == 0          # same rack
    assert a1.distance_to(spine) == 2       # same room, different row


def test_unknown_levels_never_count_as_a_match(inventory):
    """Two devices with no recorded room are not in the same room, they are unplaced.
    Guessing here would produce confident wrong placements."""
    placed = inventory.get("sw-aa-s01-p1").location
    unplaced = inventory.get("sw-bb-s01-p1").location
    assert placed.distance_to(unplaced) == UNRELATED
    assert Location().distance_to(Location()) == UNRELATED


def test_selection_filters(inventory):
    assert len(inventory.select(site_category="dc")) == 4
    assert [d.hostname for d in inventory.select(site="bb")] == ["sw-bb-s01-p1"]
    assert [d.hostname for d in inventory.select(hostname_pattern="^m")] == ["m01-aa"]
    assert [d.hostname for d in inventory.select(role="dc-spine")] == ["sw-aa-s03-wu"]


def test_gaps_are_reported_not_fatal(inventory):
    assert inventory.gaps() == {"m01-aa": ["role"]}


def test_only_hostname_is_required(tmp_path):
    path = tmp_path / "bare.csv"
    path.write_text("hostname\nsw-x\nsw-y\n")
    loaded = Inventory.load_csv(path)
    assert len(loaded) == 2
    assert loaded.get("sw-x").target == "sw-x"
    assert set(loaded.gaps()) == {"sw-x", "sw-y"}


def test_missing_hostname_column_is_an_error(tmp_path):
    path = tmp_path / "bad.csv"
    path.write_text("site,rack\naa,B12\n")
    with pytest.raises(InventoryError, match="no hostname column"):
        Inventory.load_csv(path)


def test_duplicate_hostname_is_an_error(tmp_path):
    path = tmp_path / "dupe.csv"
    path.write_text("hostname\nsw-x\nsw-x\n")
    with pytest.raises(InventoryError, match="duplicate hostname"):
        Inventory.load_csv(path)


def test_missing_file_is_an_error(tmp_path):
    with pytest.raises(InventoryError, match="no inventory file"):
        Inventory.load_csv(tmp_path / "nope.csv")


def test_unrecognised_columns_are_preserved(tmp_path):
    path = tmp_path / "extra.csv"
    path.write_text("hostname,owner_team\nsw-x,netops\n")
    assert Inventory.load_csv(path).get("sw-x").extra == {"owner_team": "netops"}
