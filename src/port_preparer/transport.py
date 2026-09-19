"""How we talk to a switch.

SSH is the only real transport. REST/RESTCONF is deliberately *not* implemented -- it is
behind this interface so it can be added without touching anything above, which is what the
user asked for ("focus on ssh, keep rest in your head").

`MockTransport` replays captured output, so every parser, the discovery engine and the audit
report are testable with no network at all.
"""

from __future__ import annotations

import re
from abc import ABC, abstractmethod
from pathlib import Path


class TransportError(RuntimeError):
    pass


def command_slug(command: str) -> str:
    """`'show vlan i-sid'` -> `'show_vlan_i_sid'`, the fixture filename convention."""
    return re.sub(r"[^a-z0-9]+", "_", command.strip().lower()).strip("_")


class Transport(ABC):
    """A session against one device. Read-only unless `send_config` is used."""

    def __init__(self, host: str) -> None:
        self.host = host

    @abstractmethod
    def run(self, command: str) -> str:
        """Run a `show` command and return its raw output."""

    def send_config(self, lines: list[str]) -> str:  # pragma: no cover - Phase 3
        raise NotImplementedError("configuration push is Phase 3")

    def __enter__(self):
        return self

    def __exit__(self, *exc_info) -> None:
        self.close()

    def close(self) -> None:
        pass


class MockTransport(Transport):
    """Replays captured output from a directory of `<command_slug>.txt` files."""

    def __init__(self, directory: str | Path, host: str | None = None) -> None:
        self.directory = Path(directory)
        if not self.directory.is_dir():
            raise TransportError(f"no such capture directory: {self.directory}")
        super().__init__(host or self.directory.name)

    def run(self, command: str) -> str:
        path = self.directory / f"{command_slug(command)}.txt"
        if not path.exists():
            raise TransportError(f"no capture for {command!r} in {self.directory} (expected {path.name})")
        return path.read_text()


class SSHTransport(Transport):
    """netmiko over SSH, device_type `extreme_vsp`.

    Credentials are passed in per session and never persisted -- the engineer is prompted
    once per run and they live in memory only.
    """

    def __init__(
        self,
        host: str,
        username: str,
        password: str,
        *,
        port: int = 22,
        timeout: int = 30,
        read_timeout: int = 90,
    ) -> None:
        super().__init__(host)
        try:
            from netmiko import ConnectHandler  # noqa: PLC0415 - optional dependency
        except ImportError as exc:  # pragma: no cover - depends on install extras
            raise TransportError(
                "netmiko is required to reach a real switch: pip install 'port-preparer[ssh]'"
            ) from exc

        self._read_timeout = read_timeout
        try:
            self._connection = ConnectHandler(
                device_type="extreme_vsp",
                host=host,
                username=username,
                password=password,
                port=port,
                conn_timeout=timeout,
                fast_cli=False,
            )
        except Exception as exc:  # netmiko raises a family of these
            raise TransportError(f"cannot connect to {host}: {exc}") from exc

    def run(self, command: str) -> str:
        try:
            return self._connection.send_command(command, read_timeout=self._read_timeout)
        except Exception as exc:
            raise TransportError(f"{self.host}: command {command!r} failed: {exc}") from exc

    def close(self) -> None:
        connection = getattr(self, "_connection", None)
        if connection is not None:
            try:
                connection.disconnect()
            except Exception:  # pragma: no cover - best effort on teardown
                pass
