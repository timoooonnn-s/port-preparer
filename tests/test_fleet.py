"""Fleet collection. One device's failure must never cost the other 299."""

from __future__ import annotations

from conftest import FLEET, LAB
from port_preparer.fleet import collect_fleet
from port_preparer.transport import MockTransport, TransportError


def factory(hostname: str):
    if hostname == "sw-down":
        raise TransportError("connection refused")
    if hostname == "sw-lab":
        return MockTransport(LAB, host=hostname)
    return MockTransport(FLEET / hostname, host=hostname)


def test_one_unreachable_device_does_not_stop_the_crawl():
    fleet = collect_fleet(["sw-syn-a1", "sw-down", "sw-syn-a2"], factory, workers=3)
    assert {r.hostname for r in fleet.reached} == {"sw-syn-a1", "sw-syn-a2"}
    assert [r.hostname for r in fleet.failed] == ["sw-down"]
    assert "connection refused" in fleet.results["sw-down"].error


def test_a_parser_explosion_on_one_device_is_contained(monkeypatch):
    import port_preparer.fleet as fleet_module

    real_discover = fleet_module.discover

    def explode(collection):
        if collection.host == "sw-syn-a1":
            raise ValueError("synthetic parser failure")
        return real_discover(collection)

    monkeypatch.setattr(fleet_module, "discover", explode)
    fleet = collect_fleet(["sw-syn-a1", "sw-syn-a2"], factory, workers=1)
    assert [r.hostname for r in fleet.failed] == ["sw-syn-a1"]
    assert "synthetic parser failure" in fleet.results["sw-syn-a1"].error
    assert [r.hostname for r in fleet.reached] == ["sw-syn-a2"]


def test_coverage_and_timestamp_are_reported():
    fleet = collect_fleet(["sw-syn-a1", "sw-down"], factory, workers=2)
    assert fleet.coverage() == "1/2 device(s) reached"
    assert fleet.as_of


def test_duplicate_hostnames_are_collected_once():
    fleet = collect_fleet(["sw-syn-a1", "sw-syn-a1"], factory, workers=2)
    assert len(fleet.results) == 1


def test_serial_and_concurrent_paths_agree():
    serial = collect_fleet(["sw-syn-a1", "sw-syn-a2"], factory, workers=1)
    parallel = collect_fleet(["sw-syn-a1", "sw-syn-a2"], factory, workers=4)
    assert sorted(serial.results) == sorted(parallel.results)
    assert {h: len(r.state.isids) for h, r in serial.results.items()} == {
        h: len(r.state.isids) for h, r in parallel.results.items()
    }


def test_no_devices_is_not_an_error():
    fleet = collect_fleet([], factory)
    assert fleet.coverage() == "no devices"
