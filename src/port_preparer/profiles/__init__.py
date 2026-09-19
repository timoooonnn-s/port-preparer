"""Profile loading and the inheritance chain.

Profiles are data (decision 0005): they set values and toggles, and contain no conditionals.
Adding a scenario is a YAML edit, not a code change.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

DEFAULT_PROFILE_PATH = Path(__file__).with_name("default.yaml")

#: Order in which layers are merged. Later layers win.
CHAIN = ("global", "site_categories", "sites", "roles", "scenarios")


class ProfileError(ValueError):
    pass


def _deep_merge(base: dict[str, Any], overlay: dict[str, Any]) -> dict[str, Any]:
    merged = copy.deepcopy(base)
    for key, value in overlay.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = copy.deepcopy(value)
    return merged


@dataclass
class ResolvedProfile:
    """The effective settings for one (site category, role, scenario) combination."""

    values: dict[str, Any] = field(default_factory=dict)
    layers: list[str] = field(default_factory=list)

    @property
    def access_port_requirements(self) -> dict[str, Any]:
        return dict(self.values.get("access_port", {}))

    @property
    def reserved_vlan_ids(self) -> set[int]:
        return set(self.values.get("reserved_vlan_ids", []))

    @property
    def mtu(self) -> int | None:
        return self.values.get("mtu")


@dataclass
class ProfileSet:
    raw: dict[str, Any]
    source: Path | None = None

    @classmethod
    def load(cls, path: str | Path | None = None) -> ProfileSet:
        target = Path(path) if path is not None else DEFAULT_PROFILE_PATH
        if not target.exists():
            raise ProfileError(f"no profile file at {target}")
        data = yaml.safe_load(target.read_text()) or {}
        if not isinstance(data, dict):
            raise ProfileError(f"{target}: top level must be a mapping")
        return cls(raw=data, source=target)

    def resolve(
        self,
        *,
        site_category: str | None = None,
        site: str | None = None,
        role: str | None = None,
        scenario: str | None = None,
    ) -> ResolvedProfile:
        values = copy.deepcopy(self.raw.get("global", {}) or {})
        layers = ["global"]
        for group, name in (
            ("site_categories", site_category),
            ("sites", site),
            ("roles", role),
            ("scenarios", scenario),
        ):
            if name is None:
                continue
            layer = (self.raw.get(group) or {}).get(name)
            if layer is None:
                raise ProfileError(f"no {group[:-1].replace('_', ' ')} named {name!r} in the profile set")
            values = _deep_merge(values, layer)
            layers.append(f"{group}.{name}")
        return ResolvedProfile(values=values, layers=layers)

    def role_for_hostname(self, hostname: str | None) -> str | None:
        """Match a hostname against role patterns. This is how `m*` management switches are
        recognised, from data rather than a hard-coded rule."""
        if not hostname:
            return None
        import re

        for name, definition in (self.raw.get("roles") or {}).items():
            pattern = (definition or {}).get("hostname_pattern")
            if pattern and re.search(pattern, hostname, re.IGNORECASE):
                return name
        return None

    def scenario_names(self) -> list[str]:
        return sorted((self.raw.get("scenarios") or {}).keys())
