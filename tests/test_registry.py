"""The registry: allocation atomicity, provenance, and refusing to invent things."""

from __future__ import annotations

import pytest
from port_preparer.model import Environment
from port_preparer.registry import (
    AllocationConflict,
    PortRecord,
    Registry,
    RegistryError,
    ServiceRecord,
)


def test_allocation_is_atomic_and_names_the_holder(registry):
    registry.allocate_for_vlan(695, Environment.PROD, name="payroll-prod", application="payroll")
    with pytest.raises(AllocationConflict) as caught:
        registry.allocate_for_vlan(695, Environment.PROD, name="someone-else")
    assert "2500695" in str(caught.value)
    assert caught.value.holder.name == "payroll-prod"


def test_the_same_vlan_in_two_environments_is_two_services(registry):
    prod = registry.allocate_for_vlan(695, Environment.PROD, name="a")
    nonprod = registry.allocate_for_vlan(695, Environment.NONPROD, name="b")
    assert (prod.i_sid, nonprod.i_sid) == (2500695, 2700695)


def test_reserved_vlan_cannot_be_allocated(registry):
    with pytest.raises(RegistryError):
        registry.allocate_for_vlan(31, Environment.PROD, name="nope")


def test_records_round_trip_through_yaml(registry):
    registry.allocate_for_vlan(
        700, Environment.PROD, name="svc", owner="netops", ticket="CHG-1", description="d"
    )
    loaded = registry.get_service(2500700)
    assert (loaded.name, loaded.owner, loaded.ticket, loaded.description) == ("svc", "netops", "CHG-1", "d")
    assert loaded.created_by and loaded.created_at


def test_update_refuses_to_create(registry):
    with pytest.raises(RegistryError, match="not allocated"):
        registry.update_service(ServiceRecord(i_sid=2500999, name="typo"))


def test_upsert_never_overwrites_an_existing_service(registry):
    registry.allocate_service(ServiceRecord(i_sid=2500695, name="original", owner="netops"))
    record, created = registry.upsert_service(ServiceRecord(i_sid=2500695, name="from-the-network"))
    assert created is False
    assert record.name == "original"


def test_port_claims_are_atomic(registry):
    registry.claim_port(PortRecord(hostname="sw-a", port_id="1/43", i_sids=[2500695]))
    with pytest.raises(AllocationConflict, match="already claimed"):
        registry.claim_port(PortRecord(hostname="sw-a", port_id="1/43"))


def test_port_path_is_filesystem_safe(registry):
    registry.claim_port(PortRecord(hostname="sw-a", port_id="2/1/1"))
    assert registry.get_port("sw-a", "2/1/1") is not None
    assert registry.port_path("sw-a", "2/1/1").name == "2-1-1.yaml"


def test_release_port(registry):
    registry.claim_port(PortRecord(hostname="sw-a", port_id="1/1"))
    assert registry.release_port("sw-a", "1/1") is True
    assert registry.release_port("sw-a", "1/1") is False


def test_ports_awaiting_promotion_finds_forgotten_phase_a_ports(registry):
    registry.claim_port(PortRecord(hostname="sw-a", port_id="1/1", stage="build"))
    registry.claim_port(PortRecord(hostname="sw-a", port_id="1/2", stage="production"))
    assert [p.port_id for p in registry.ports_awaiting_promotion()] == ["1/1"]


def test_harvested_services_are_flagged_as_lacking_identity(registry):
    registry.allocate_service(ServiceRecord(i_sid=2500695, name="ISID-2500695", status="harvested"))
    assert registry.get_service(2500695).identity_known is False
    assert any("no recorded purpose" in w for w in registry.warnings())


def test_a_named_service_with_an_owner_counts_as_identified(registry):
    registry.allocate_service(ServiceRecord(i_sid=2500695, name="x", owner="netops"))
    assert registry.get_service(2500695).identity_known is True


def test_unknown_fields_from_a_future_version_are_preserved_not_dropped(registry):
    path = registry.service_path(2500695)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("i_sid: 2500695\nname: x\nsome_future_field: keepme\n")
    record = registry.get_service(2500695)
    assert any("some_future_field" in note for note in record.notes)


def test_lock_is_reentrant_across_sequential_uses(registry):
    with registry.lock():
        registry.allocate_service(ServiceRecord(i_sid=2500001))
    with registry.lock():
        registry.allocate_service(ServiceRecord(i_sid=2500002))
    assert {s.i_sid for s in registry.services()} == {2500001, 2500002}


def test_empty_registry_is_not_an_error(tmp_path):
    assert Registry(tmp_path / "nothing").services() == []
    assert Registry(tmp_path / "nothing").ports() == []
