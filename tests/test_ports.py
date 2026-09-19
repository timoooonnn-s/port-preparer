"""Port identifier handling. Nothing may assume `slot/port`."""

from __future__ import annotations

import doctest

import pytest
from port_preparer import ports


def test_doctests():
    assert doctest.testmod(ports, raise_on_error=True).failed == 0


@pytest.mark.parametrize(
    ("spec", "expected"),
    [
        ("1/45", ["1/45"]),
        ("2/1/1", ["2/1/1"]),
        ("1/1-1/4", ["1/1", "1/2", "1/3", "1/4"]),
        ("1/1-1/2,1/23-1/24", ["1/1", "1/2", "1/23", "1/24"]),
        ("NONE", []),
        ("-", []),
    ],
)
def test_expand(spec, expected):
    assert ports.expand(spec) == expected


def test_expand_three_part_range_spans_ports_and_channels():
    # `1/17/1-1/18/4` appears in real 9.x output for channelized sub-ports.
    assert ports.expand("1/17/1-1/18/4") == [
        "1/17/1", "1/17/2", "1/17/3", "1/17/4",
        "1/18/1", "1/18/2", "1/18/3", "1/18/4",
    ]


def test_full_chassis_spec_from_running_config():
    assert len(ports.expand("1/1-1/48,2/1-2/6")) == 54


def test_unparseable_token_is_reported_not_raised():
    ids, bad = ports.expand_tolerant("1/1,wat,1/3")
    assert ids == ["1/1", "1/3"]
    assert bad == ["wat"]


def test_compress_round_trips_mixed_shapes():
    assert ports.compress(["1/1", "1/2", "1/3", "1/23", "2/1/1"]) == "1/1-1/3,1/23,2/1/1"


def test_normalise_strips_leading_zeros():
    assert ports.normalise("01/05") == "1/5"
