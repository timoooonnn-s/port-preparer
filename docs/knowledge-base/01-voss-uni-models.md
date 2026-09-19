# 01 — VOSS UNI models: the four ways a port attaches to a service

**Revised 2026-09-19** after reading real device output in
`timoooonnn-s/switch-migrator@claude/migration-toolkit-ideas-3ld3ld:tests/fixtures`.
Most of this entry moved from `[ASSUMED]` to `[VERIFIED-FIXTURE]`.

New confidence marker used here:
**[VERIFIED-FIXTURE]** — matches captured output from the user's own estate. Stronger than
`[ASSUMED]`, weaker than a lab pass we ran ourselves, because the capture is a snapshot and
may not cover every release.

---

## The decisive discovery: we do not need a rule, we can detect

The user could not give a rule for "Switched UNI or platform VLAN?" (question B1) — and it
turns out we do not need one. `show i-sid` reports the model per I-SID in its `TYPE`
column: `[VERIFIED-FIXTURE: voss/show_i_sid.txt]`

```
ISID                PORT               MLT
ID       TYPE       INTERFACES         INTERFACES         ORIGIN     ISID NAME
10100    ELAN       c100:1/10,c100:1/11 c100:2            CONFIG     Server-100
10200    ELAN       -                  c200:2             CONFIG     Server-200
20300    ELAN       c300:1/12          -                  CONFIG     Special-300
2502201  CVLAN      c2201:1/36         -                  CONFIG     quarantaine

c: customer vid   u: untagged-traffic
```

- `TYPE = ELAN`  → Switched UNI (flex-uni). The service lives in an `i-sid <x> elan` block.
- `TYPE = CVLAN` → platform VLAN mapped to an I-SID, the classic model.
- Binding notation: `c<vid>:<port>` is a tagged C-VID binding, `u:<port>` is untagged
  traffic, and an MLT binding prints the MLT id in the MLT column (`c100:2` = MLT 2).

`show interfaces gigabitethernet i-sid` gives the same per *port*, with an `ISID TYPE`
column and a `MAC SUNI` flag. `[VERIFIED-FIXTURE]`

**Consequence for the tool:** the model is discovered, never assumed. The engine reads the
switch, decides which model that switch/port already speaks, and then either follows it or
refuses and explains. This retires the "give me a rule" problem entirely.

---

## A. Platform VLAN with I-SID (CVLAN UNI) `[VERIFIED-FIXTURE]`

Observed in production on `gx-11-s72-p1` (VSP-7254XSQ, 8.10.9.0): 37 service VLANs, each
with an I-SID, `FLEX-UNI disable` on every MLT.

```
vlan create 695 name "E010035016000_21" type port-mstprstp 0
vlan i-sid 695 2500695
vlan members add 695 1/45 portmember
interface GigabitEthernet 1/45
    encapsulation dot1q        # omit for untagged
exit
```

## B. Switched UNI / Flex UNI `[VERIFIED-FIXTURE]`

From a real `show running-config` (VSP-7254XSQ, 8.10.9.0). This is the exact ordering the
box itself emits, and it is load-bearing — VOSS writes port config in two passes:

```
#
# PORT CONFIGURATION - PHASE I
#
interface GigabitEthernet 1/4
encapsulation dot1q
exit

#
# PORT CONFIGURATION - PHASE II
#
interface GigabitEthernet 1/4
default-vlan-id 0
flex-uni enable
no shutdown
slpp-guard enable timeout 0
spanning-tree mstp edge-port true
exit

#
# I-SID CONFIGURATION
#
i-sid 2500695 elan
c-vid 695 port 1/4
untagged-traffic port 1/4
exit
i-sid 2510735 elan
c-vid 735 port 1/4
exit
```

Facts this pins down:

1. **`encapsulation dot1q` comes before `flex-uni enable`**, in a separate interface block.
   The generator must emit phase I and phase II separately or risk a rejected line.
   `[VERIFIED-FIXTURE — worth one lab confirmation that the single-block form actually fails]`
2. **`default-vlan-id 0`** accompanies flex-uni. This is how the port stops having a PVID.
3. **A port carries several I-SIDs at once, and tagged + untagged simultaneously.** Port 1/4
   has I-SID 2500695 both as `c-vid 695` *and* `untagged-traffic`, plus I-SID 2510735 as
   `c-vid 735`. This is the answer to "sometimes with and sometimes without VLAN tagging":
   it is not either/or per port, it is per binding. **The data model must therefore be a
   list of bindings per port, not a tagging mode per port.** The Architect regards this as
   the single most important modelling constraint found so far.
4. `slpp-guard enable timeout 0` and `spanning-tree mstp edge-port true` appear on the
   access port — evidence for the hygiene set in entry 03.

### On an MLT (the dual-homed server case) `[VERIFIED-FIXTURE]`

```
mlt 197 enable name "srv-lag"
interface mlt 197
smlt
lacp enable key 197
flex-uni enable
exit
```

**`lacp enable key <n>` uses the MLT id as the key.** Observed as 197/197. The tool should
derive the key from the MLT id rather than allocating separately.

## C. Transparent Port UNI (T-UNI, `elan-transparent`) `[ASSUMED]`

The user believes this exists in the estate (question B2) but **no fixture contains an
`elan-transparent` I-SID**. Syntax below is still unverified prior:

```
i-sid 2500200 elan-transparent
    port 1/2
exit
```

Port reportedly must be out of all VLANs with spanning tree off. **Open: we need one real
example before the tool will emit this.** Until then the engine will *parse and report*
T-UNI but refuse to *create* it.

## D. Auto-sense `[CONFIRMED BY USER — not in scope]`

User states auto-sense is not configured except for ZTP. The engine will still **detect**
`auto-sense enable` on a target port and refuse to touch it, because a ZTP-onboarding port
is exactly the port someone will accidentally aim this tool at.

---

## Newly discovered, previously unknown to the council

### DVR is deployed `[VERIFIED-FIXTURE]` — nobody mentioned this

`boot config flags dvr-leaf-mode` is set in the captured running-config, and
`show dvr interfaces` returns populated rows mapping L2ISID→VLAN→gateway:

```
INTERFACE        MASK            L3ISID  VRFID  L2ISID    VLAN  GW-IPV4
10.1.100.1       255.255.255.0   0       0      10100     100   10.1.100.1
172.105.0.1      255.255.255.0   55501   5      1501050   1050  172.105.0.1
```

Distributed Virtual Routing leaf mode constrains what may be configured on a node. The
Critic has escalated this as a blocking question: if DC access switches are DVR leaves, the
tool must know, because DVR leaf restrictions are a class of failure that only shows up at
apply time.

### Port identifiers have two *and* three part forms `[VERIFIED-FIXTURE]`

`1/45`, but also `2/1/1` and ranges like `1/17/1-1/18/4` (channelized sub-ports). Any port
spec parser that assumes `slot/port` is wrong. The 9.x fixtures exist specifically to pin
this.

### vIST rides the fabric, and its VLAN breaks the I-SID numbering rule `[VERIFIED-FIXTURE]`

`show virtual-ist` gives peer `10.41.8.10` on VLAN 31; VLAN 31 is named
`E010041008008_30` (= 10.41.8.8/30, so .9/.10 — consistent) and carries I-SID **1531100**,
which does *not* follow the "prefix + 4-digit VLAN id" convention. B-VIDs are 4051/4052.
MLT 1 (`MLT001.svi.108.116`, ports 1/8 + 1/16) carries only 4051/4052 — the ISIS NNI to the
peer. The tool must treat vIST VLAN, B-VLANs and the NNI MLT as **untouchable**.

## Still to verify in the first lab pass

1. Does the single-block `encapsulation dot1q` + `flex-uni enable` form actually fail?
2. Are flex-uni and platform-VLAN membership truly mutually exclusive per release
   (8.10, 9.1, 9.3, 9.4)?
3. Must the I-SID exist before the `c-vid ... port` binding, and what is the error text?
4. Which transitions bounce traffic, and does the port need shutting down.
5. What a live service does when the model is changed underneath it (the convert path).
6. On an SMLT pair: which lines must match exactly on both vIST peers.
7. Real T-UNI output.
