# port-preparer

Create and audit configured access ports on Extreme VOSS / Fabric Connect switches.

Runs on one central automation host. Prompts for your RADIUS credentials, holds them in
memory only, and talks to switches over SSH. Scope is VOSS 8.10+ / 9.x. No ERS, no EXOS.

**Status: Phase 1.** The read-only audit works. Nothing in this tool writes to a switch yet.

## Install

```sh
python3 -m venv .venv && . .venv/bin/activate
pip install -e '.[ssh,dev]'      # drop [ssh] if you only work from captures
```

Python 3.11+. `netmiko` is only needed to reach a real switch; the parsers, the audit engine
and the whole test suite run without it.

## Use

Audit a live switch. Read-only — it runs `show` commands and nothing else.

```sh
port-preparer audit --host sw-aa-s01-p1 --site-category dc
```

Audit from captured output, with no network at all:

```sh
port-preparer audit --capture tests/fixtures/voss --site-category dc
port-preparer audit --capture tests/fixtures/voss --json | jq '.ports."1/4"'
```

Capture a switch's output for the test suite. **This is how output we have never seen becomes
a fixture** — see `docs/CAPTURE-REQUESTS.md` for what is wanted:

```sh
port-preparer capture --host sw-aa-s01-p1 --output captures/
```

Compute or explain a convention:

```sh
port-preparer conventions --vlan 695                    # -> i-sid 2500695
port-preparer conventions --isid 1531100                # -> infrastructure prefix
port-preparer conventions --vlan-name E010041008008_30  # -> 10.41.8.8/30
port-preparer conventions --port 1/10                   # -> MLT 410
```

`audit` exits 0 when nothing needs a human, 1 when there are findings, 2 on a connection or
usage error.

## What the audit tells you

Per port: the **detected UNI model** (switched-UNI / platform-VLAN / T-UNI / NNI / unused /
unknown), link state, MLT membership, every I-SID binding, and the LLDP neighbour.

Findings are graded, and the grades matter:

| Severity | Meaning |
|---|---|
| `error` | Actively wrong or dangerous. A human must look. |
| `warning` | Drift between sources, or a convention broken after the rule existed. |
| `legacy` | Predates the current convention. **Not a defect.** |
| `unknown` | We could not determine this, and say so rather than guess. |
| `info` | Context worth printing (DVR leaf, vIST pair, reserved objects). |

The estate is older than its own conventions. A port built before a rule existed is `legacy`,
never `error` — conflating the two would report 300 switches as broken and the tool would be
ignored.

`unknown` exists for the same reason in reverse: if the collection did not include the
commands that would reveal a service, a port is reported as `unknown`, **not** as free. A tool
that says "this port is available" because it failed to ask is worse than one that admits it
does not know.

## Objects the tool refuses to touch

The vIST VLAN and its I-SID, SPBM B-VLANs, ISIS/NNI ports and the NNI MLT, any port with
`auto-sense enable` (ZTP owns it), and any port already in an I-SID the request does not
mention. Refusals are loud and explain themselves.

## Conventions it knows

* **I-SID** = `<prefix><vlan padded to 4>`. Prefix encodes the environment: `250`/`251` prod,
  `270`/`271` non-prod, `299` special. Within an environment the variants are equivalent; the
  tool generates the lower one and treats the other as legacy. Infrastructure I-SIDs (e.g.
  `1531100` on the vIST VLAN) follow their own scheme and are never generated.
* **VLAN name** = `<LETTER><12-digit network><_prefixlen>`, e.g. `E010035016000_21` is
  10.35.16.0/21. The letter's meaning is unknown, so the tool decodes and verifies names but
  never invents a letter.
* **MLT id** = `4xx` where `xx` is the port number, for new LAGs. Ids outside that block are
  legacy. **LACP key equals the MLT id.**
* VLANs 1 and 31 are reserved estate-wide (31 is the inter-switch trunk VLAN).

## Development

```sh
PYTHONPATH=src python3 -m pytest -q
```

112 tests, no network required. Fixtures under `tests/fixtures/` are real captured output with
hostnames replaced by **equal-length** substitutes — several tables are parsed by column
offset, so changing a name's width corrupts the fixture.

## Documentation

* `docs/PLAN.md` — what we are building and the phase order.
* `docs/OPEN-QUESTIONS.md` — what is still unknown.
* `docs/CAPTURE-REQUESTS.md` — output we need from the lab, and why.
* `docs/knowledge-base/` — VOSS behaviour, with a confidence marker on every claim.
* `council/` — the review roster and the decision log, including recorded dissents.
