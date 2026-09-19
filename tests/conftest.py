from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

FIXTURES = Path(__file__).parent / "fixtures"
LAB = FIXTURES / "voss"
PROD = FIXTURES / "voss_prod" / "sw-aa-s01-p1"
PROD_PARTIAL = FIXTURES / "voss_prod" / "sw-aa-s01-p1-partial"
NINE_X = FIXTURES / "voss_9x"
FLEET = FIXTURES / "fleet"


def read(directory: Path, name: str) -> str:
    return (directory / name).read_text()


@pytest.fixture
def lab_state():
    from port_preparer.collect import collect
    from port_preparer.discover import discover
    from port_preparer.transport import MockTransport

    return discover(collect(MockTransport(LAB)))


@pytest.fixture
def prod_state():
    from port_preparer.collect import collect
    from port_preparer.discover import discover
    from port_preparer.transport import MockTransport

    return discover(collect(MockTransport(PROD)))


@pytest.fixture
def fleet_survey():
    """The synthetic two-switch fleet, whose inconsistencies are all deliberate."""
    from port_preparer.fleet import collect_fleet
    from port_preparer.services import survey
    from port_preparer.transport import MockTransport

    hosts = ["sw-syn-a1", "sw-syn-a2"]
    fleet = collect_fleet(hosts, lambda h: MockTransport(FLEET / h, host=h), workers=2)
    return survey(fleet)


@pytest.fixture
def registry(tmp_path):
    from port_preparer.registry import Registry

    store = Registry(tmp_path / "registry")
    store.initialise()
    return store
