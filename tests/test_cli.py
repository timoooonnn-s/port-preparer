"""CLI smoke tests. No network: every case runs against a capture."""

from __future__ import annotations

import json

from conftest import LAB, PROD
from port_preparer.cli import app
from typer.testing import CliRunner

runner = CliRunner()


def streams(result) -> str:
    """Everything the command emitted. Diagnostics go to stderr so that --json stays
    machine-parseable, so a test about an error message must look at both."""
    text = result.stdout or ""
    try:
        text += result.stderr or ""
    except (ValueError, AttributeError):  # some click versions merge the streams
        pass
    return text


def test_audit_against_a_capture_renders_and_exits_nonzero_when_findings_exist():
    result = runner.invoke(app, ["audit", "--capture", str(LAB), "--site-category", "dc"])
    assert result.exit_code == 1            # findings present
    assert "lab-l01" in result.stdout
    assert "switched-uni" in result.stdout
    assert "model-mixed" in result.stdout


def test_audit_json_output_is_machine_readable():
    result = runner.invoke(app, ["audit", "--capture", str(LAB), "--json"])
    payload = json.loads(result.stdout)
    assert payload["hostname"] == "lab-l01"
    assert payload["dvr_leaf"] is True
    assert payload["ports"]["1/4"]["model"] == "switched-uni"
    assert {"i_sid": 2500695, "c_vid": None} in payload["ports"]["1/4"]["bindings"]
    assert payload["ok"] is False


def test_audit_reports_unknown_rather_than_free_ports_on_a_partial_capture():
    result = runner.invoke(app, ["audit", "--capture", str(PROD), "--json"])
    payload = json.loads(result.stdout)
    assert sorted(payload["missing_evidence"]) == ["i-sid-bindings", "vlan-members"]
    assert all(port["model"] == "unknown" for port in payload["ports"].values())


def test_host_and_capture_are_mutually_exclusive():
    result = runner.invoke(app, ["audit", "--capture", str(LAB), "--host", "sw1"])
    assert result.exit_code != 0


def test_missing_capture_directory_fails_cleanly():
    result = runner.invoke(app, ["audit", "--capture", "/nonexistent/path"])
    assert result.exit_code == 2
    assert "no such capture directory" in streams(result)


def test_conventions_command_computes_an_isid():
    result = runner.invoke(app, ["conventions", "--vlan", "695"])
    assert "2500695" in result.stdout


def test_conventions_command_decomposes_an_infrastructure_isid():
    result = runner.invoke(app, ["conventions", "--isid", "1531100"])
    assert "infra" in result.stdout


def test_conventions_command_decodes_a_vlan_name():
    result = runner.invoke(app, ["conventions", "--vlan-name", "E010041008008_30"])
    assert "10.41.8.8/30" in result.stdout


def test_conventions_command_refuses_the_reserved_vlan():
    result = runner.invoke(app, ["conventions", "--vlan", "31"])
    assert result.exit_code == 2


def test_missing_ssh_extra_is_reported_before_prompting_for_credentials(monkeypatch):
    """Typing a RADIUS password and then being told netmiko is absent is a bad first run."""
    import port_preparer.cli as cli

    monkeypatch.setattr(cli, "ssh_available", lambda: False)

    def fail(*args, **kwargs):  # pragma: no cover - must never be reached
        raise AssertionError("credentials were requested despite no usable transport")

    monkeypatch.setattr(cli.getpass, "getpass", fail)
    monkeypatch.setattr(cli.typer, "prompt", fail)

    result = runner.invoke(app, ["audit", "--host", "sw-aa-s01-p1"])
    assert result.exit_code == 2
    assert "netmiko is required" in streams(result)
    assert "--capture" in streams(result)


# --- discover-services -------------------------------------------------------------

def test_discover_services_against_a_capture_root():
    from conftest import FLEET

    result = runner.invoke(app, ["discover-services", "--capture-root", str(FLEET)])
    assert result.exit_code == 0
    assert "isid-name-conflict" in result.stdout
    assert "isid-orphan" in result.stdout


def test_discover_services_json_is_parseable_despite_progress_output():
    """Regression: the crawl progress line used to be printed to stdout, which made --json
    unparseable when piped."""
    from conftest import FLEET

    result = runner.invoke(app, ["discover-services", "--capture-root", str(FLEET), "--json"])
    payload = json.loads(result.stdout)
    assert payload["coverage"] == "2/2 device(s) reached"
    assert payload["services"]["2500699"]["remote_endpoints"] == []
    assert payload["services"]["2500695"]["remote_endpoints"] == ["sw-syn-a1", "sw-syn-a2"]
    assert any(f["code"] == "isid-orphan" for f in payload["findings"])


def test_discover_services_harvests_into_a_registry(tmp_path):
    from conftest import FLEET
    from port_preparer.registry import Registry

    store = tmp_path / "registry"
    result = runner.invoke(app, [
        "discover-services", "--capture-root", str(FLEET),
        "--registry", str(store), "--harvest", "--json",
    ])
    payload = json.loads(result.stdout)
    assert payload["harvested"]
    assert {s.i_sid for s in Registry(store).services()} == set(payload["harvested"])
    assert all(s.status == "harvested" for s in Registry(store).services())


def test_harvest_without_a_registry_is_refused():
    from conftest import FLEET

    result = runner.invoke(app, ["discover-services", "--capture-root", str(FLEET), "--harvest"])
    assert result.exit_code == 2
    assert "--registry" in streams(result)


def test_capture_root_and_inventory_are_mutually_exclusive(tmp_path):
    from conftest import FLEET

    inventory = tmp_path / "devices.csv"
    inventory.write_text("hostname\nsw-x\n")
    result = runner.invoke(app, [
        "discover-services", "--capture-root", str(FLEET), "--inventory", str(inventory),
    ])
    assert result.exit_code != 0


def test_discover_services_needs_a_source():
    result = runner.invoke(app, ["discover-services"])
    assert result.exit_code != 0


def test_empty_capture_root_explains_the_expected_layout(tmp_path):
    result = runner.invoke(app, ["discover-services", "--capture-root", str(tmp_path)])
    assert result.exit_code != 0
    assert "one directory per" in streams(result)
