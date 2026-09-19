"""Device inventory: the physical facts a switch cannot report.

Arrives as CSV, because that is how the user's IPAM export arrives and enriching it by hand is
the plan. Only `hostname` is required. Everything else is optional, and the loader *reports*
what is missing rather than refusing to start -- an inventory that must be complete before the
tool runs is an inventory that never gets used.
"""

from __future__ import annotations

import csv
import re
from dataclasses import dataclass, field
from pathlib import Path

#: Coarse-to-fine location hierarchy. Distance between two devices is the index of the first
#: level at which they differ, which makes "nearest" cheap to compute and easy to explain.
LOCATION_LEVELS = ("site", "building", "room", "row", "rack")

#: Returned when two locations share nothing, or when either is unknown.
UNRELATED = len(LOCATION_LEVELS)


class InventoryError(ValueError):
    pass


@dataclass(frozen=True)
class Location:
    site: str | None = None
    building: str | None = None
    room: str | None = None
    row: str | None = None
    rack: str | None = None
    rack_unit: int | None = None

    @property
    def known(self) -> bool:
        return any(getattr(self, level) for level in LOCATION_LEVELS)

    def distance_to(self, other: Location) -> int:
        """0 = same rack, 1 = same row, ... `UNRELATED` = nothing in common or unknown.

        Unknown levels never count as a match: two devices with no recorded room are not in the
        same room, they are simply unplaced. Guessing here would produce confident wrong
        placements, which is the failure mode the Operator cares most about.
        """
        for index, level in enumerate(reversed(LOCATION_LEVELS)):
            mine, theirs = getattr(self, level), getattr(other, level)
            if mine and theirs and mine == theirs:
                return index
        return UNRELATED

    def describe(self) -> str:
        parts = [f"{level}={getattr(self, level)}" for level in LOCATION_LEVELS if getattr(self, level)]
        if self.rack_unit is not None:
            parts.append(f"u={self.rack_unit}")
        return " ".join(parts) or "location unknown"


@dataclass
class InventoryDevice:
    """An inventory record. Distinct from `DeviceState`, which is what the switch reports."""

    hostname: str
    site_category: str | None = None      # dc | office | branch
    role: str | None = None               # dc-access | management-switch | ...
    location: Location = field(default_factory=Location)
    mgmt_address: str | None = None
    platform: str | None = None
    vist_peer: str | None = None
    notes: str | None = None
    extra: dict[str, str] = field(default_factory=dict)

    @property
    def target(self) -> str:
        """What to actually connect to: the management address if we have one, else the name."""
        return self.mgmt_address or self.hostname

    def missing_fields(self) -> list[str]:
        gaps = [name for name in ("site_category", "role") if getattr(self, name) is None]
        if not self.location.known:
            gaps.append("location")
        return gaps


_TRUE = {"1", "true", "yes", "y"}


def _clean(value: str | None) -> str | None:
    if value is None:
        return None
    text = value.strip()
    return text or None


class Inventory:
    """A loaded set of inventory devices, keyed by hostname (case-insensitively)."""

    def __init__(self, devices: list[InventoryDevice], source: Path | None = None) -> None:
        self._devices: dict[str, InventoryDevice] = {}
        for device in devices:
            key = device.hostname.lower()
            if key in self._devices:
                raise InventoryError(f"duplicate hostname in inventory: {device.hostname}")
            self._devices[key] = device
        self.source = source

    def __len__(self) -> int:
        return len(self._devices)

    def __iter__(self):
        return iter(sorted(self._devices.values(), key=lambda d: d.hostname))

    def get(self, hostname: str) -> InventoryDevice | None:
        return self._devices.get(hostname.lower())

    def select(
        self,
        *,
        site: str | None = None,
        site_category: str | None = None,
        role: str | None = None,
        hostname_pattern: str | None = None,
    ) -> list[InventoryDevice]:
        chosen = list(self)
        if site is not None:
            chosen = [d for d in chosen if (d.location.site or "").lower() == site.lower()]
        if site_category is not None:
            chosen = [d for d in chosen if (d.site_category or "").lower() == site_category.lower()]
        if role is not None:
            chosen = [d for d in chosen if (d.role or "").lower() == role.lower()]
        if hostname_pattern is not None:
            pattern = re.compile(hostname_pattern, re.IGNORECASE)
            chosen = [d for d in chosen if pattern.search(d.hostname)]
        return chosen

    def gaps(self) -> dict[str, list[str]]:
        """Which devices are missing which optional-but-wanted fields."""
        return {d.hostname: gaps for d in self if (gaps := d.missing_fields())}

    # --- loading ------------------------------------------------------------------

    #: Column aliases, so an IPAM export does not have to be renamed by hand first.
    ALIASES = {
        "hostname": {"hostname", "host", "name", "device", "switch"},
        "site_category": {"site_category", "category", "sitetype", "site_type"},
        "role": {"role", "device_role", "function"},
        "site": {"site", "location_site", "standort"},
        "building": {"building", "gebaeude", "gebäude"},
        "room": {"room", "raum"},
        "row": {"row", "reihe"},
        "rack": {"rack", "cabinet", "schrank"},
        "rack_unit": {"rack_unit", "u", "ru", "he"},
        "mgmt_address": {"mgmt_address", "mgmt_ip", "ip", "ip_address", "management_ip"},
        "platform": {"platform", "model", "box_type", "type"},
        "vist_peer": {"vist_peer", "peer", "ist_peer", "smlt_peer"},
        "notes": {"notes", "note", "comment", "description"},
    }

    @classmethod
    def _map_headers(cls, fieldnames: list[str]) -> dict[str, str]:
        """Map each known field to the actual column name present in the file."""
        normalised = {name: re.sub(r"[^a-z0-9_]+", "_", (name or "").strip().lower()) for name in fieldnames}
        mapping: dict[str, str] = {}
        for field_name, aliases in cls.ALIASES.items():
            for original, cleaned in normalised.items():
                if cleaned in aliases:
                    mapping[field_name] = original
                    break
        return mapping

    @classmethod
    def load_csv(cls, path: str | Path) -> Inventory:
        target = Path(path)
        if not target.exists():
            raise InventoryError(f"no inventory file at {target}")
        with target.open(newline="", encoding="utf-8-sig") as handle:
            sample = handle.read(4096)
            handle.seek(0)
            try:
                dialect = csv.Sniffer().sniff(sample, delimiters=",;\t")
            except csv.Error:
                dialect = csv.excel
            reader = csv.DictReader(handle, dialect=dialect)
            if not reader.fieldnames:
                raise InventoryError(f"{target}: no header row")
            mapping = cls._map_headers(list(reader.fieldnames))
            if "hostname" not in mapping:
                raise InventoryError(
                    f"{target}: no hostname column found. Looked for any of: "
                    f"{', '.join(sorted(cls.ALIASES['hostname']))}"
                )
            devices: list[InventoryDevice] = []
            for row in reader:
                hostname = _clean(row.get(mapping["hostname"]))
                if hostname is None:
                    continue
                unit = _clean(row.get(mapping.get("rack_unit", ""), ""))
                devices.append(
                    InventoryDevice(
                        hostname=hostname,
                        site_category=_clean(row.get(mapping.get("site_category", ""), "")),
                        role=_clean(row.get(mapping.get("role", ""), "")),
                        location=Location(
                            site=_clean(row.get(mapping.get("site", ""), "")),
                            building=_clean(row.get(mapping.get("building", ""), "")),
                            room=_clean(row.get(mapping.get("room", ""), "")),
                            row=_clean(row.get(mapping.get("row", ""), "")),
                            rack=_clean(row.get(mapping.get("rack", ""), "")),
                            rack_unit=int(unit) if unit and unit.isdigit() else None,
                        ),
                        mgmt_address=_clean(row.get(mapping.get("mgmt_address", ""), "")),
                        platform=_clean(row.get(mapping.get("platform", ""), "")),
                        vist_peer=_clean(row.get(mapping.get("vist_peer", ""), "")),
                        notes=_clean(row.get(mapping.get("notes", ""), "")),
                        extra={
                            key: value
                            for key, value in row.items()
                            if key and key not in mapping.values() and _clean(value)
                        },
                    )
                )
        return cls(devices, source=target)
