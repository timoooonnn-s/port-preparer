"""The registry: what the switches cannot tell us.

Allocations, service identity, and provenance. **Not** a cache of device state -- reality is
re-read from the device every time (decision 0011).

Storage is one small YAML file per allocated object, under a directory held in git. That is not
a compromise for lack of a database, it is what makes allocation safe without one:

* **Claiming a number is atomic.** `open(..., O_CREAT|O_EXCL)` on the object's own path either
  creates it or raises `FileExistsError`. Two engineers racing for I-SID 2500695: one wins, the
  other gets a clear error naming who holds it. No lock, no server, no round trip.
* **No git merge conflicts.** Two people adding two services touch two different files. One
  shared registry file would collide every time.
* **`flock` covers multi-step work.** Allocating an I-SID *and* an MLT id *and* claiming two
  ports must be all-or-nothing; that takes one lock for the duration.

Sound because there is a single central automation host. The registry directory must live on
**local disk** on that host -- `O_EXCL` is weaker on NFS, and nothing here could detect that.
"""

from __future__ import annotations

import fcntl
import getpass
import os
import socket
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field, fields
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

import yaml

from .conventions import ConventionError, classify_isid, isid_for_new_service
from .model import Environment

SERVICES_DIR = "services"
PORTS_DIR = "ports"
LOCK_FILE = ".lock"


class RegistryError(RuntimeError):
    pass


class AllocationConflict(RegistryError):
    """The object is already allocated. Carries the holder so the error can name it."""

    def __init__(self, message: str, holder: Any | None = None) -> None:
        super().__init__(message)
        self.holder = holder


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _whoami() -> str:
    try:
        return f"{getpass.getuser()}@{socket.gethostname()}"
    except Exception:  # pragma: no cover - getuser can fail in odd environments
        return "unknown"


@dataclass
class ServiceRecord:
    """One allocated I-SID and what it is for.

    `snapshot` records where the service was *seen* at a moment in time. It is explicitly a
    snapshot with an `as_of`, never authority -- the device is always authority.
    """

    i_sid: int
    vlan_id: int | None = None
    environment: str | None = None
    name: str | None = None
    description: str | None = None
    owner: str | None = None
    application: str | None = None
    ticket: str | None = None
    #: reserved = allocated but not yet on any switch; deployed = in service;
    #: harvested = imported from what was already configured, identity not yet filled in.
    status: str = "reserved"
    created_at: str = field(default_factory=_now)
    created_by: str = field(default_factory=_whoami)
    snapshot: dict[str, Any] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ServiceRecord:
        known = {f.name for f in fields(cls)}
        unknown = {k: v for k, v in data.items() if k not in known}
        record = cls(**{k: v for k, v in data.items() if k in known})
        if unknown:
            # Never discard a field a future version wrote; keep it visible.
            record.notes.append(f"unrecognised fields preserved: {sorted(unknown)}")
        return record

    @property
    def identity_known(self) -> bool:
        """True once a human has said what this service is actually for."""
        return bool(self.description or self.application or self.owner)


@dataclass
class PortRecord:
    """Provenance for a port this tool configured. Answers 'is this mine to remove?'."""

    hostname: str
    port_id: str
    scenario: str | None = None
    i_sids: list[int] = field(default_factory=list)
    mlt_id: int | None = None
    stage: str | None = None          # build | production -- the two-phase lifecycle
    device_class: str | None = None   # linux | windows | esx | ...
    ticket: str | None = None
    configured_at: str = field(default_factory=_now)
    configured_by: str = field(default_factory=_whoami)
    notes: list[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> PortRecord:
        known = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in data.items() if k in known})


def _port_slug(port_id: str) -> str:
    return port_id.replace("/", "-")


def _dump(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(yaml.safe_dump(payload, sort_keys=False, allow_unicode=True))


def _create_exclusive(path: Path, payload: dict[str, Any]) -> None:
    """Atomically create `path`. Raises FileExistsError if it is already there."""
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
    try:
        with os.fdopen(handle, "w") as stream:
            stream.write(yaml.safe_dump(payload, sort_keys=False, allow_unicode=True))
    except BaseException:
        path.unlink(missing_ok=True)
        raise


class Registry:
    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)

    # --- lifecycle ----------------------------------------------------------------

    def initialise(self) -> Path:
        (self.root / SERVICES_DIR).mkdir(parents=True, exist_ok=True)
        (self.root / PORTS_DIR).mkdir(parents=True, exist_ok=True)
        return self.root

    @contextmanager
    def lock(self, timeout_note: str = "") -> Iterator[None]:
        """Exclusive lock for multi-step allocations. One automation host, so this is real."""
        self.initialise()
        lock_path = self.root / LOCK_FILE
        handle = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o644)
        try:
            try:
                fcntl.flock(handle, fcntl.LOCK_EX)
            except OSError as exc:  # pragma: no cover - platform dependent
                raise RegistryError(f"cannot lock the registry{timeout_note}: {exc}") from exc
            yield
        finally:
            try:
                fcntl.flock(handle, fcntl.LOCK_UN)
            finally:
                os.close(handle)

    # --- services -----------------------------------------------------------------

    def service_path(self, i_sid: int) -> Path:
        return self.root / SERVICES_DIR / f"{i_sid}.yaml"

    def get_service(self, i_sid: int) -> ServiceRecord | None:
        path = self.service_path(i_sid)
        if not path.exists():
            return None
        data = yaml.safe_load(path.read_text()) or {}
        if not isinstance(data, dict):
            raise RegistryError(f"{path}: expected a mapping")
        data.setdefault("i_sid", i_sid)
        return ServiceRecord.from_dict(data)

    def services(self) -> list[ServiceRecord]:
        directory = self.root / SERVICES_DIR
        if not directory.is_dir():
            return []
        out: list[ServiceRecord] = []
        for path in sorted(directory.glob("*.yaml")):
            stem = path.stem
            if not stem.isdigit():
                continue
            record = self.get_service(int(stem))
            if record is not None:
                out.append(record)
        return out

    def allocate_service(self, record: ServiceRecord) -> ServiceRecord:
        """Claim an I-SID. Atomic: the loser of a race gets `AllocationConflict`."""
        self.initialise()
        path = self.service_path(record.i_sid)
        try:
            _create_exclusive(path, asdict(record))
        except FileExistsError as exc:
            holder = self.get_service(record.i_sid)
            held_by = f" (held by {holder.name or 'an unnamed service'}" if holder else ""
            if holder and holder.created_by:
                held_by += f", allocated by {holder.created_by} at {holder.created_at}"
            if held_by:
                held_by += ")"
            raise AllocationConflict(
                f"I-SID {record.i_sid} is already allocated{held_by}", holder=holder
            ) from exc
        return record

    def allocate_for_vlan(
        self,
        vlan_id: int,
        environment: Environment,
        **identity: Any,
    ) -> ServiceRecord:
        """Allocate the canonical I-SID for `vlan_id` in `environment`.

        If the canonical number is taken, this does **not** silently pick another: a different
        service holding the number an engineer expects is something a human must see.
        """
        try:
            i_sid = isid_for_new_service(vlan_id, environment)
        except ConventionError as exc:
            raise RegistryError(str(exc)) from exc
        record = ServiceRecord(
            i_sid=i_sid, vlan_id=vlan_id, environment=environment.value, **identity
        )
        return self.allocate_service(record)

    def update_service(self, record: ServiceRecord) -> ServiceRecord:
        """Overwrite an existing record. Refuses to create, so a typo cannot invent a service."""
        path = self.service_path(record.i_sid)
        if not path.exists():
            raise RegistryError(f"I-SID {record.i_sid} is not allocated; use allocate_service")
        _dump(path, asdict(record))
        return record

    def upsert_service(self, record: ServiceRecord) -> tuple[ServiceRecord, bool]:
        """Returns (record, created). Used by harvesting, which is idempotent by nature."""
        if self.service_path(record.i_sid).exists():
            return self.get_service(record.i_sid), False  # type: ignore[return-value]
        return self.allocate_service(record), True

    # --- ports --------------------------------------------------------------------

    def port_path(self, hostname: str, port_id: str) -> Path:
        return self.root / PORTS_DIR / hostname / f"{_port_slug(port_id)}.yaml"

    def get_port(self, hostname: str, port_id: str) -> PortRecord | None:
        path = self.port_path(hostname, port_id)
        if not path.exists():
            return None
        data = yaml.safe_load(path.read_text()) or {}
        return PortRecord.from_dict(data)

    def claim_port(self, record: PortRecord) -> PortRecord:
        """Record that this tool owns a port. Atomic, so two runs cannot both claim it."""
        self.initialise()
        path = self.port_path(record.hostname, record.port_id)
        try:
            _create_exclusive(path, asdict(record))
        except FileExistsError as exc:
            holder = self.get_port(record.hostname, record.port_id)
            raise AllocationConflict(
                f"{record.hostname} port {record.port_id} is already claimed"
                + (f" by {holder.configured_by} at {holder.configured_at}" if holder else ""),
                holder=holder,
            ) from exc
        return record

    def release_port(self, hostname: str, port_id: str) -> bool:
        path = self.port_path(hostname, port_id)
        if not path.exists():
            return False
        path.unlink()
        return True

    def ports(self, hostname: str | None = None) -> list[PortRecord]:
        directory = self.root / PORTS_DIR
        if not directory.is_dir():
            return []
        pattern = f"{hostname}/*.yaml" if hostname else "*/*.yaml"
        out: list[PortRecord] = []
        for path in sorted(directory.glob(pattern)):
            data = yaml.safe_load(path.read_text()) or {}
            out.append(PortRecord.from_dict(data))
        return out

    def ports_awaiting_promotion(self) -> list[PortRecord]:
        """Phase-A ports nobody ever promoted -- the commonest failure of a two-step process."""
        return [p for p in self.ports() if p.stage == "build"]

    # --- health -------------------------------------------------------------------

    def warnings(self) -> list[str]:
        """Conditions that quietly weaken the atomicity guarantee."""
        out: list[str] = []
        mounts = Path("/proc/mounts")
        if mounts.exists():
            try:
                resolved = str(self.root.resolve())
                for line in mounts.read_text().splitlines():
                    parts = line.split()
                    if len(parts) < 3:
                        continue
                    mount_point, fs_type = parts[1], parts[2]
                    if fs_type in {"nfs", "nfs4", "cifs", "smb3"} and resolved.startswith(mount_point):
                        out.append(
                            f"the registry is on a {fs_type} mount ({mount_point}); "
                            "O_EXCL atomicity is not guaranteed there, so allocation races are "
                            "possible. Move it to local disk on the automation host."
                        )
            except OSError:  # pragma: no cover
                pass
        unnamed = [s.i_sid for s in self.services() if not s.identity_known]
        if unnamed:
            out.append(
                f"{len(unnamed)} service(s) have no recorded purpose, owner or application "
                f"(first: {unnamed[0]}). These are harvested entries awaiting a human."
            )
        return out
