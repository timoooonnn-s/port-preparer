# Current plan

Owner: the Drafter. This file is the single source of truth for what we are doing now.
Revised 2026-09-19 after the user's answers and the fixture review.

## What we are building

A Python 3.11 tool that runs on one central automation host, prompts the engineer for their
RADIUS credentials (never stored), logs into Extreme VOSS switches over SSH, and creates
correctly configured access ports — one at a time through an interactive wizard, or many at
once from a batch file. It always shows a diff first; writing requires an explicit flag. It
backs up before writing, verifies after, saves config, and commits the rendered intent to git
as the record of what was asked for.

## Settled constraints

| Decision | Value |
|---|---|
| Execution | Tool logs in and pushes; `--dry-run` is the default, `--apply` is explicit |
| Safety | `show running-config` backup before every write; `save config` after success |
| Host | One central automation host |
| UX | Interactive wizard **and** multi-port batch in one authenticated session |
| UNI model | **Detected per switch/port**, never assumed — both models are in the estate |
| Transport | SSH (netmiko `extreme_vsp`); REST kept behind a transport interface, not built |
| Credentials | Prompted per run, held in memory only |
| Language | Python 3.11, no Ansible |
| Record | Rendered intent committed to git |
| Scope | VOSS only. No ERS, no EXOS |
| Releases | 8.10+, 9.1, 9.3, 9.4 — version-gated capability matrix |
| Estate | ~300 switches, 50+ sites: 2 DC, 3 large offices, 40+ branches, each a config variant |
| Inventory | IPAM export enriched by hand, landing as CSV |
| First milestone | Read-only audit |
| I-SID prefix | `250`/`251` prod, `270`/`271` non-prod, `299` special; variants equivalent |
| Legacy | The estate predates its rules: non-conforming is `legacy`, never `error` |
| Lab | The user installs and runs it; `capture` feeds output back as fixtures |

## Architecture

Templates are **data, not code** — the Operator's requirement, since scenario four will
arrive and nobody should have to edit Python for it.

```
port_preparer/
  model/       domain types: Device, Port, Binding, Service, Intent, ChangePlan
  inventory/   CSV loader (IPAM export + manual overrides), site/role resolution, m* rule
  profiles/    YAML profiles and scenario templates; inheritance chain below
  transport/   Transport interface; SSHTransport (netmiko), MockTransport (fixtures)
  collect/     which show commands to run, per release
  parse/       VOSS show-output parsers, table-aware and release-tolerant
  discover/    parsed output -> DeviceState, including which UNI model each port speaks
  render/      Intent -> ordered VOSS command list (phase-aware: see KB entry 01)
  diff/        DeviceState vs Intent -> ChangePlan
  apply/       backup, ordered execution, post-verify, save, rollback script
  audit/       existing ports vs profile -> compliance report
  record/      git commit of rendered intent
  cli/         typer app: audit, plan, apply, wizard, batch
```

Profile inheritance, most general to most specific:
`global -> site-category (dc|office|branch) -> site -> device-role -> scenario -> port override`

### Two modelling rules the Architect will not compromise on

1. **A port holds a list of bindings, not a tagging mode.** The fixtures show port 1/4 with
   I-SID 2500695 as both `c-vid 695` and `untagged-traffic`, plus I-SID 2510735 as `c-vid
   735`. Any model with a single `tagged: bool` per port is already wrong.
2. **Port identifiers are opaque strings with two *or* three parts.** `1/45` and `2/1/1` and
   ranges like `1/17/1-1/18/4` all occur. No `slot/port` assumptions anywhere.

### Objects the tool must refuse to touch

vIST VLAN and its I-SID, SPBM B-VLANs (4051/4052), ISIS/NNI ports and the NNI MLT,
any port with `auto-sense enable` (ZTP), and any port already in an I-SID the intent does not
mention. Refusal is loud and explains itself.

## Phases

- **Phase 0 — skeleton. DONE.** Domain model, port-id handling, conventions, mock transport,
  13 command parsers, running-config parser, 112 tests, no network needed.
- **Phase 1 — `audit` (read-only). DONE.** Collects, parses, detects the UNI model per port,
  grades findings, and emits tables or JSON. `capture` writes fixtures for the test suite.
  Still wanted: real profile values per site category (capture request 4).
- **Phase 2 — `plan`.** Render intent, produce the diff, write nothing. *Needs Q1 only for
  proposing MLT ids; I-SIDs can now be proposed, and engineer-supplied values validate
  without it.* **Next.**
- **Phase 3 — `apply`.** Backup, ordered execution, post-verify, save, rollback script, git
  record.
- **Phase 4 — batch and SMLT pairs.** Multi-port, and dual-homed servers as one transaction
  across both vIST peers with a defined half-failure behaviour.
- **Phase 5 — decommission.** Same model in reverse; the operation that hurts most by hand.

## Next action

Build Phase 2: the renderer and the diff. Everything it needs is settled except the
MLT-id rule (Q1), which only affects *proposing* an id for a new LAG.
