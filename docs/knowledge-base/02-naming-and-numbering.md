# 02 — Naming and numbering conventions, as observed

Derived by the Researcher on 2026-09-19 from the production fixtures. Where the evidence
contradicts what the user told us, that is called out — the Critic insists we do not silently
prefer one source over the other.

## I-SID numbering `[VERIFIED-FIXTURE, rule partially unknown]`

User statement: *"i-sid numbering has different leading numbers (250, 251, 270, 271, 299 and
a few others) and then 4 digits for the vlan id"*.

The fixtures confirm the shape exactly — `<prefix><vlan, zero-padded to 4>`:

| VLAN | I-SID | VLAN name | Prefix |
|---|---|---|---|
| 174 | 2510174 | `X010041002000_24` | 251 |
| 695 | 2500695 | `E010035016000_21` | 250 |
| 696 | 2510696 | `E010034064000_24` | 251 |
| 699 | 2500699 | `E010035024000_23` | 250 |
| 735 | 2510735 | `E010035008000_21` | 251 |
| 2200 | 2502200 | `E010030004000_26` | 250 |
| 2246 | 2512246 | `X010054064064_27` | 251 |
| 2901 | 2512901 | `X010030008000_26` | 251 |

**Solved (2026-09-19, by the user).** The prefix encodes the **environment**:

| Prefix | Meaning |
|---|---|
| 250, 251 | production |
| 270, 271 | non-production |
| 299 | a special area, neither prod nor non-prod |

Within an environment the two variants are, verbatim, "the engineer's mood — nothing more,
nothing less". So 250 and 251 are equivalent. The tool generates the canonical lower one and
grades the other `legacy` rather than rewriting it (see decision 0010 for the Critic's
reservation about that).

This is what unblocked *proposing* an I-SID rather than only validating one.

**Exception confirmed:** VLAN 31 → I-SID **1531100**, which does not fit the rule at all. The
user confirms VLAN 31 is a reserved inter-switch trunk VLAN estate-wide. Infrastructure I-SIDs
use their own scheme; the tool recognises the `153` prefix as infrastructure, never generates
one, and refuses to touch vIST/B-VLAN/NNI objects.

## VLAN naming `[VERIFIED-FIXTURE — fully deterministic]`

Format: `<LETTER><12 digits><_prefixlen>`, where the 12 digits are the four octets of the
network address zero-padded to three digits each.

```
E010041008008_30  ->  10.41.8.8/30     (vIST transfer net; peer .10 confirmed)
E010035016000_21  ->  10.35.16.0/21
E192168012000_22  ->  192.168.12.0/22
X010054064064_27  ->  10.54.64.64/27
E010030004064_27  ->  10.30.4.64/27
```

This is a clean, reversible encoding — the engine can generate the name from a prefix and
verify existing names against their subnet, which is a free correctness check worth having.

**Still unsolved: the leading letter.** `E`, `X` and `R` are all in use, and the user does not
know what they distinguish either. Consequence for the tool: it decodes and verifies names, and
**never invents a letter** — generating a name requires the caller to supply one. Two exceptions
to the whole scheme: VLAN 99 is `quarantine` and VLAN 1 is `Default`.

## MLT — the user's rule and the device disagree `[CONTRADICTION]`

User statement: *"MLT ID is 4xx, where xx is the port ID"*.

What `show mlt` actually reports on `gx-11-s72-p1`:

| MLT ID | Name | Ports | Type | LACP | Neighbour |
|---|---|---|---|---|---|
| 1 | `MLT001.svi.108.116` | 1/8, 1/16 | trunk, norm | disable | vIST NNI to `gx-11-s72-p2`, B-VIDs only |
| 35 | `MLT035.s.1/2/23/24` | 1/1-1/2, 1/23-1/24 | trunk, smlt | disable | uplinks to two VSP-7400 |
| 38 | `s129` | 1/29 | trunk, smlt | disable | ERS 5952 stack |
| 196 | `f110` | 1/10 | trunk, smlt | enable | HPE DL580 |
| 197 | `f143` | 1/43 | trunk, smlt | enable | HPE DL380 |
| 198 | `f115` | 1/15 | trunk, smlt | enable | HPE DL380 |
| 199 | `f145` | 1/45 | access, smlt | enable | HPE DL380 Gen9 |
| 200 | `f146` | 1/46 | access, smlt | enable | HPE DL380 Gen9 |

The port number is encoded in the **name**, not the id: `f110` = port 1/10, `f143` = 1/43,
`s129` = 1/29. The ids themselves run 196–200 sequentially. A `4xx` scheme would have
produced MLT 410 for port 1/10, and does not appear anywhere in this capture.

**Resolved as a sequencing question, not a contradiction.** The user confirms the fixtures are
older than the rules they gave us: `4xx` is what **new** ports must use, and 196–200 is history.
The tool therefore generates `4xx` and grades anything outside that block `legacy`. Pinned as a
test (`test_prod_capture_confirms_the_mlt_id_convention_conflict`) so it cannot be forgotten.

Still open as Q1: whether the id is `4xx` for a *two-part* port id only — the convention has no
defined answer for channelized sub-ports like `2/1/1`, where the tool currently refuses and
demands an explicit id.

Name prefixes observed: `f` on server LAGs, `s` on switch/stack links, `svi` on the vIST
MLT. Guessing at the semantics would be a mistake; asked as part of Q1.

## Other verified facts worth writing down

- **`lacp enable key <n>` uses the MLT id as the key** (`mlt 197` / `key 197`). Derive, do
  not allocate separately.
- **MLT type `access` vs `trunk`** tracks `ENCAP DOT1Q disable` vs `enable`. MLT 199/200 are
  untagged access LAGs to servers; 196–198 are tagged with a single VLAN each.
- **Port descriptions are not set** — the `DESCRIPTION` column shows the transceiver type
  (`10GbSR`, `Gbic1000BaseT`, `10GbNone`), which is read-only inventory data, not a name.
  The separate `NAME` field is set only on uplinks and infrastructure links (`to-core-01`,
  `vIST-a`, `vIST-b`, `core-s74-w5`), matching what the user said.
- **MTU is 1950 on every port** in both captures. Treat as the site default, not a per-port
  decision, until told otherwise.
- **Hostname convention:** `gx-11-s72-p1` / `-p2` are the vIST pair; `gx-11-s74-wu` / `-wv`
  are the upstream VSP-7400 pair. The `m*` management-switch rule the user gave (question
  E2) is consistent with this being a structured naming scheme, but we have no `m*` sample
  yet — asked as Q4.
- **Platform/release spread confirmed in one rack:** VSP-7254XSQ on 8.10.9.0 and
  VSP-7400-48Y-8C on 9.3.1.0, peering with each other. A version-gated capability matrix is
  not theoretical; it is needed on day one.
