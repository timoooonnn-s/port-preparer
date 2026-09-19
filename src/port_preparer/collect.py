"""Which commands to run against a device, and gathering their output.

`--save-raw` writes every response to a directory in the `MockTransport` layout, so a lab run
produces fixtures we can build and test against without network access. That is the only
mechanism by which output we have never seen (T-UNI, 9.4 releases, management switches)
reaches the test suite, so it is not an add-on: it is the point.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .transport import Transport, TransportError, command_slug


@dataclass(frozen=True)
class Command:
    cli: str
    #: False when a command is expected to be missing on some platforms or releases, so its
    #: absence is recorded rather than reported as a failure.
    required: bool = True
    note: str = ""


#: Ordered so that the cheap, always-present commands run first: if a device is going to
#: refuse us, we find out before spending a minute on it.
AUDIT_COMMANDS: tuple[Command, ...] = (
    Command("show running-config", note="authoritative configuration and the backup baseline"),
    Command("show vlan basic"),
    Command("show vlan i-sid"),
    Command("show vlan members"),
    Command("show i-sid", note="the TYPE column is how the UNI model is detected"),
    Command("show interfaces gigabitethernet i-sid"),
    Command(
        "show interfaces gigabitethernet interface",
        required=False,
        note="same Port Interface section that `show interfaces gigabitethernet` carries; "
        "collected separately because some releases truncate the combined output",
    ),
    Command("show interfaces gigabitethernet"),
    Command("show mlt"),
    Command("show virtual-ist", required=False, note="absent on non-SMLT nodes"),
    Command("show dvr interfaces", required=False, note="absent when DVR is not configured"),
    Command("show lldp neighbor summary", required=False),
)


@dataclass
class Collection:
    host: str
    raw: dict[str, str]
    errors: dict[str, str]

    def save(self, directory: str | Path) -> Path:
        """Write the capture in `MockTransport` layout."""
        target = Path(directory)
        target.mkdir(parents=True, exist_ok=True)
        for command, output in self.raw.items():
            (target / f"{command_slug(command)}.txt").write_text(output)
        if self.errors:
            lines = [f"{command}: {message}" for command, message in sorted(self.errors.items())]
            (target / "_collection_errors.txt").write_text("\n".join(lines) + "\n")
        return target


def collect(
    transport: Transport,
    commands: tuple[Command, ...] = AUDIT_COMMANDS,
) -> Collection:
    """Run every command, recording failures instead of aborting.

    A half-successful collection still produces a usable report -- it just has to be able to
    say "unknown" rather than "absent", which is why errors are kept alongside the output.
    """
    raw: dict[str, str] = {}
    errors: dict[str, str] = {}
    for command in commands:
        try:
            raw[command.cli] = transport.run(command.cli)
        except TransportError as exc:
            if command.required:
                errors[command.cli] = str(exc)
            else:
                errors[command.cli] = f"optional command unavailable: {exc}"
    return Collection(host=transport.host, raw=raw, errors=errors)
