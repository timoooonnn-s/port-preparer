"""Collecting from many devices at once.

Twelve commands across ~300 switches serially is roughly 25-75 minutes, so this is concurrent
with a cap. Two properties matter more than speed:

* **One device's failure never stops the crawl.** A switch that is down, refuses the login, or
  runs a release whose output we cannot parse produces a recorded error and the run continues.
* **Every result carries when it was taken.** A fleet report is a snapshot of 300 devices read
  over several minutes, not an instant. Presenting it without an `as_of` invites people to treat
  it as current (decision 0011).
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Callable, Iterable

from .collect import AUDIT_COMMANDS, Collection, Command, collect
from .discover import DiscoveryReport, discover
from .model import DeviceState
from .transport import Transport, TransportError

#: Conservative by default: this runs against production, and 8 concurrent SSH sessions is
#: already more than the team would ever open by hand.
DEFAULT_WORKERS = 8


@dataclass
class DeviceResult:
    hostname: str
    state: DeviceState | None = None
    report: DiscoveryReport | None = None
    collection: Collection | None = None
    error: str | None = None
    as_of: str = ""

    @property
    def ok(self) -> bool:
        return self.error is None and self.state is not None


@dataclass
class FleetResult:
    results: dict[str, DeviceResult] = field(default_factory=dict)
    started_at: str = ""
    finished_at: str = ""

    @property
    def reached(self) -> list[DeviceResult]:
        return [r for r in self.results.values() if r.ok]

    @property
    def failed(self) -> list[DeviceResult]:
        return [r for r in self.results.values() if not r.ok]

    @property
    def as_of(self) -> str:
        """The span the snapshot covers. Deliberately a range, because that is the truth."""
        if self.started_at == self.finished_at:
            return self.started_at
        return f"{self.started_at} .. {self.finished_at}"

    def coverage(self) -> str:
        total = len(self.results)
        return f"{len(self.reached)}/{total} device(s) reached" if total else "no devices"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def collect_fleet(
    hostnames: Iterable[str],
    transport_factory: Callable[[str], Transport],
    *,
    commands: tuple[Command, ...] = AUDIT_COMMANDS,
    workers: int = DEFAULT_WORKERS,
    on_done: Callable[[DeviceResult], None] | None = None,
) -> FleetResult:
    """Collect and discover across many devices concurrently.

    `transport_factory` is given a hostname and returns an open transport; it is called inside
    the worker thread, so connection setup is parallel too. Credentials are closed over by the
    caller and never stored here.
    """
    targets = list(dict.fromkeys(hostnames))
    fleet = FleetResult(started_at=_now())

    def work(hostname: str) -> DeviceResult:
        try:
            transport = transport_factory(hostname)
        except TransportError as exc:
            return DeviceResult(hostname=hostname, error=str(exc), as_of=_now())
        except Exception as exc:  # a factory can fail in ways netmiko does not wrap
            return DeviceResult(hostname=hostname, error=f"{type(exc).__name__}: {exc}", as_of=_now())
        try:
            with transport:
                collection = collect(transport, commands)
            state, report = discover(collection)
            return DeviceResult(
                hostname=hostname, state=state, report=report, collection=collection, as_of=_now()
            )
        except Exception as exc:
            # A parser or discovery bug on one device must not lose the other 299.
            return DeviceResult(
                hostname=hostname, error=f"{type(exc).__name__}: {exc}", as_of=_now()
            )

    if workers <= 1:
        for hostname in targets:
            result = work(hostname)
            fleet.results[hostname] = result
            if on_done is not None:
                on_done(result)
    else:
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {pool.submit(work, hostname): hostname for hostname in targets}
            for future in as_completed(futures):
                result = future.result()
                fleet.results[result.hostname] = result
                if on_done is not None:
                    on_done(result)

    fleet.finished_at = _now()
    return fleet
