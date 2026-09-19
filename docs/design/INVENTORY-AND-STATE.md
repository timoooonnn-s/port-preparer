# Inventory, allocation, and the statefile question

Brainstorming record, 2026-09-20. Raised by the user: where does inventory live, how do we fix
I-SID naming chaos, how does the tool decide *which* switch to configure, and would a
Terraform-style statefile help?

This is the most consequential design decision in the project, so the council took it apart
before writing any code.

---

## 1. There are three kinds of truth, and conflating them is the trap

| Kind | Example | Can a switch tell us? |
|---|---|---|
| **Reality** | port 1/43 is in MLT 197 with I-SID 2500695 | **Yes, completely, in seconds** |
| **Intent** | this service is the payroll app's non-prod segment, owner X, ticket Y | No |
| **Physical world** | that switch is in rack B12, room 2, patched to panel P4 | Almost never |

Nearly every bad decision available here comes from storing one of these in the place meant
for another. The rule the council proposes:

> **Reality is always re-read from the device. Never cache it as authority.**
> **Store only what the device cannot tell you.**

## 2. Why a Terraform-style statefile is the wrong model here

Terraform state does four jobs. Score them against this project:

| Terraform's job | Needed here? |
|---|---|
| Map a logical name to an opaque cloud resource ID | **No.** `sw-aa-s01-p1` port `1/43` *is* the address. There is no opaque id to remember. |
| Cache attributes so you can diff without calling the API | **No, and actively harmful.** Reading a VOSS switch is cheap and always more truthful than a cache. |
| Record what the tool owns, so destroy is safe | **Yes. This is the real one.** |
| Ordering and locking | **Partly.** Locking matters for *allocation*, not for device state. |

Terraform's model assumes **Terraform is the only writer**. The user's own description of the
team is "a lot of work by hand or with low level automation". That assumption will be false
for years, possibly forever. A state cache that can silently disagree with the network is a
liability in that world, and Terraform's characteristic failure — *"state is out of sync,
refresh required"* — would be actively dangerous when the thing you are about to touch is a
live server port.

So the shape is **inverted** relative to Terraform:

```
Terraform:   desired ──diff──▶ state (cache) ──apply──▶ reality
This tool:   desired ──diff──▶ reality (read live, every time)
                  ▲
                  └── registry supplies names, numbers, intent, ownership
                      (only what reality cannot report)
```

**Proposed hard rule, and the Critic wants it enforced in code:** the tool must never refuse
to act because its registry disagrees with a device. The device wins, the registry is
corrected, and the discrepancy is recorded as a finding. There is no "refresh" state a human
has to resolve before working.

We deliberately avoid the word "state" for the persistent store, because the word drags the
Terraform mental model with it. Call it the **registry**.

## 3. What the registry must hold

Four things, and nothing else:

**a. Allocations.** I-SID numbers and names, VLAN ids, MLT ids. The decisive argument: an
I-SID that is *reserved but not yet deployed* exists nowhere on any switch. Without a
registry, two engineers working the same afternoon allocate the same number, and nothing
catches it until traffic does.

**b. Service intent.** What a service is *for*: owner, application, environment, ticket,
description, which sites it should reach. This is the thing that has never been written down
anywhere, and its absence *is* the naming chaos in question 2.

**c. Ownership and provenance.** Which ports this tool configured, when, by whom, under which
request. Needed for safe decommission ("is this port mine to remove?") and for the audit
trail. Cannot be derived.

**d. Physical facts.** Site, building, room, row, rack, rack-unit, and cabling. Plus the
device's **role** — DC access, DC spine, office access, branch access, management (`m*`).

**e. Lifecycle position.** Notably the two-phase build (section 8): "this port is in phase A,
awaiting promotion to production" is a fact that exists on no switch. This is the one genuinely
statefile-shaped item in the whole design, and it is small.

## 4. Where it should live

**Constraint from the user (2026-09-20): NetBox/Nautobot is not available and should not be
designed for.** That is not a deferral, it is a boundary. So the registry has to be robust
standalone and permanently — and the concurrent-allocation problem the council flagged is ours to
solve, not something a database will fix later.

The enabling fact: **there is one central automation host.** Every engineer runs the tool there.
That makes file-level atomicity sufficient, because there is exactly one filesystem involved.

### The design: one file per allocated object, in git

```
registry/
  services/2500695.yaml            # one file per I-SID
  services/2700695.yaml
  ports/sw-aa-s01-p1/1-43.yaml     # provenance: what we configured, when, by whom, why
  devices.csv                      # the IPAM export, enriched by hand
```

Why per-object files rather than one big file:

1. **Allocation is atomic for free.** Claiming I-SID 2500695 is
   `open(..., O_CREAT|O_EXCL)` on `services/2500695.yaml`. Two engineers racing: one wins, the
   other gets `EEXIST` and a clear error. No lock, no database, no round trip.
2. **No merge conflicts.** Separate files mean two people adding two services never collide in
   git, which one shared YAML file guarantees they would.
3. **Reviewable.** A new service is a one-file diff a colleague can read.
4. **`flock` covers the rest.** Multi-step operations (allocate an I-SID *and* an MLT id *and*
   claim two ports) take a single lock file for the duration. One host, so this is real mutual
   exclusion, not advisory hand-waving.
5. **Scale is a non-issue.** ~300 switches and a few thousand small files loads into memory in
   well under a second. No index needed.

Devices arrive as **CSV**, because that is how the user's IPAM export arrives and enriching it by
hand is the stated plan. Only `hostname` is required; everything else is optional and the loader
reports what is missing rather than refusing to start.

There is a thin seam (`Registry`, `Inventory`) so a different store could be substituted, but it
is a seam, not a plugin system — the council is not building for a backend that is not coming.

Policy stays separate: the profile YAML from decision 0005 is code-adjacent and belongs in review,
not in the registry.

## 5. The location model, for "nearest switch"

"Nearest" needs a hierarchy the tool can compute distance over:

```
site ─▶ building ─▶ room ─▶ row ─▶ rack ─▶ rack-unit
```

Distance is then a simple ladder: same rack < adjacent rack in row < same row < same room <
same building < same site < different site (usually invalid). Cheap to compute, easy to
explain, which matters because the tool must *show its reasoning*.

Two things complicate it, and both need answering:

**Patch panels are probably the real answer.** In structured cabling the question is not
"which switch is nearest to rack B12" but "which switch does rack B12's panel land on". If the
estate is patched through panels, cabling must be recorded and the location ladder is mostly
decoration. If servers are direct-attached to top-of-rack switches, the ladder is the whole
answer. These give completely different designs.

**Hostnames already encode structure.** `gx-11-s72-p1`, `gx-11-s74-wu`, `gx-11-s59-p1`, and
`m*` for management switches. If that scheme is reliable, a large part of the location and role
model can be *derived* rather than typed — which is the difference between an inventory people
maintain and one that rots. We need the scheme decoded.

## 6. Picking a port is constraint satisfaction, not a distance lookup

A candidate switch/port must satisfy all of:

1. **Location** — within acceptable distance of where the device physically is.
2. **Role** — matches the scenario. Management scenarios only on `m*`, DC scenarios only on DC
   access, and so on. Already modelled in the profile system.
3. **Service reachability** — for switched-UNI the I-SID is available anywhere the switch is a
   BEB in that fabric, which is a real advantage of Fabric Connect. For the platform-VLAN model
   the VLAN must exist *locally*. So the UNI model the switch speaks changes what is reachable,
   and the tool already detects that.
4. **Media and speed** — and this is not a boolean. From one real capture:

   | Class | Count | Meaning |
   |---|---|---|
   | empty cage (`10GbNone`, down/down) | 38 | free, but somebody must fit an optic |
   | optic fitted, link down | 1 | **free and ready today** |
   | optic fitted, link up, no service visible | 3 | something is plugged in — investigate before touching |
   | already in an MLT | 12 | in use |

   "Free port" is at least four states. A tool that reports 42 free ports when 1 is usable
   without a truck roll is not helping.
5. **Nothing is plugged in.** The three link-up ports above (all HPE ProLiants) are the
   dangerous class: physically connected, no service visible. *Caveat:* that capture lacks
   `show vlan members` and `show i-sid`, so strictly those are "no service **visible**", which
   is exactly why the audit grades them `unknown` rather than free.
6. **Placement convention** — "start on the lower switch ports with MLTs or other servers
   connected to two switches". So dual-homed allocations come off the bottom of the chassis.
   Where single-homed ports should start is not yet defined.
7. **Pair symmetry, which their own convention forces.** SMLT requires the same MLT id on both
   vIST peers. Their MLT id convention is `4xx` where `xx` is the port number. Therefore a
   dual-homed server **must use the same port number on both peers** — otherwise the two peers
   would derive different MLT ids for one LAG. That is a hard constraint derived from two rules
   that were stated separately, and it materially narrows the search: the allocator has to find
   a port number free on *both* switches simultaneously.

### The tool should propose, not decide

A wrong automatic pick costs someone a walk to the wrong rack, or worse, a patch into a live
port. The Operator's position: output the top three candidates with the reasoning and the
disqualifications, and let the engineer confirm. Full autonomy can come later, once the
proposals have been right for a few months.

### The shortcut worth building first — revised

**Superseded in part.** The original proposal was to find an already-cabled server's port via
LLDP. The user warned that LLDP data in their estate is inconsistent or absent, and measuring
their own capture confirmed it decisively: all 7 switch-to-switch links advertise a sysname,
and **0 of 8 servers do**. See `knowledge-base/03-identifying-a-device-on-a-port.md`.

So *"find the port for server web01"* is not achievable by name in this estate. The split still
holds, but the mechanism changes:

* *"Configure the port for this already-racked device"* → locate it by **MAC address** against
  the forwarding database, with LLDP chassis id as corroboration and link state as an absolute
  negative check. Multi-signal, reports a confidence, and treats *not found* and *ambiguous* as
  first-class answers. Blocked on a real FDB capture before it can be trusted.
* *"I need a port for a device that is not here yet"* → the constraint solver above, which needs
  the full location model.

`discover-services` is unaffected — it depends on none of this — so it moves to the front of the
queue on its own.

## 7. I-SID naming: fix the registry, then generate the name

What is actually on the devices today: `ISID-2510735` (auto-generated, says nothing),
`Server-100`, `quarantaine`, `Legacy-Special`. Meanwhile the *VLAN* name is rigorously
structured (`E010035016000_21` = 10.35.16.0/21) and the *I-SID number* already encodes
environment and VLAN. So the number and the VLAN name carry information; the I-SID name is the
one field that is pure chaos.

That is not a coincidence. **The I-SID name is chaotic because it is the only place anyone
could record what a service is for, and it was never designed to hold that.** The fix is not a
naming convention, it is a registry — and then the on-device name becomes *derived*, short, and
never authoritative.

Proposed approach:

1. The registry holds service identity: purpose, owner, application, environment, ticket.
2. The on-device I-SID name is generated deterministically from the registry entry, so it is
   recognisable to a human reading `show i-sid` but is never a source of truth.
3. **No big-bang migration.** The tool corrects the name whenever it touches a service.
   Cleanup happens as a by-product of normal work, which is the only cleanup that ever finishes.
4. The audit gains a check: on-device name disagrees with the registry.

*To verify on hardware:* the maximum length and legal character set for an I-SID name on 8.10
and 9.4. The generator's format depends on it, and we should not guess.

## 8. Seeding the registry from reality

The user asked for "a valid base for further buildups". The base should not be typed by hand —
it should be **harvested**. A read-only `discover-services` pass across all ~300 switches can
produce the initial registry and, more valuably, the list of things wrong with it:

* the same I-SID used for two different purposes in two places
* two I-SIDs for what is obviously one service
* I-SIDs whose number does not encode their VLAN (the audit already finds these)
* VLAN names inconsistent with their subnet (already found)
* services present on switches nobody expected
* orphans: an I-SID configured on exactly one switch, terminating nowhere

This is zero-risk, reuses the entire Phase 1 engine, and converts "our I-SIDs are chaos" from a
feeling into a list with a length. The council rates it the highest-value next thing after the
LLDP lookup.

Practical note: 12 commands × 300 switches serially is roughly 25–75 minutes. It needs
concurrency with a sane cap, and every report needs an explicit "as of" timestamp.

## 9. The two-phase build (the user's question 02)

> *"Config A gets done on the port for the linux and windows admin, so they can configure their
> server. When they are finished, the final config for the application gets deployed. I don't
> really get why this is done in two steps."*

There are four plausible reasons, and **which one it is determines whether it can be
collapsed**:

| Reason | Can it be collapsed? |
|---|---|
| The server needs a build/provisioning network (PXE, DHCP, OS install) before it has its production identity | **No** — the two phases are doing genuinely different things |
| Security: do not put an unbuilt, unpatched machine on a production segment | **No** — that is a real control, and collapsing it removes it |
| Ordering: the app team does not know the final VLAN/I-SID until the server is built | **Yes** — this is pure sequencing and the tool can carry it |
| Organisational: two teams, two tickets, two change windows | **Yes, partly** — the toil can go even if the approval gate stays |

If it is one of the first two, the right move is not to collapse it but to make it **one
declared intent with two stages** — `stage: build` then a single `promote` command — so the
engineer expresses the outcome once and the tool handles both transitions. That also removes the
commonest failure of a two-step process: phase A ports that nobody ever promoted, silently
sitting on a build network forever. The tool can list those.

Worth flagging the technical risk: promoting a port means **changing the service on a live
port**, which is item 5 on the unverified list in `knowledge-base/01-voss-uni-models.md`. We do
not yet know what that does to traffic. It needs a lab pass before the promote path is built.

And note the synthesis: a two-stage lifecycle is the strongest argument *for* a persistent
registry in this whole document, because "awaiting promotion" is a fact no switch can report.

## 10. The only inventory-maintenance strategy that works

Every inventory rots unless keeping it current is a side effect of doing the work. So:

**The tool writes back to the inventory on every apply.** Ports it configures, services it
allocates, devices it discovers. Using the tool is what keeps the inventory fresh; nobody is
asked to update a spreadsheet afterwards, because nobody ever does.

Corollary: the tool must also *report* drift between inventory and reality every time it looks
at a device, and those findings belong in the same graded audit output that already exists.

## 11. Risks the Critic wants recorded

1. **A second source of chaos.** An unmaintained NetBox is worse than no NetBox, because people
   trust it. Mitigated only by section 10.
2. **Allocation races — addressed, not deferred.** One file per allocated object with
   `O_CREAT|O_EXCL` makes claiming a number atomic, and `flock` covers multi-step operations.
   Sound because there is a single automation host. The residual risk is someone editing the
   registry by hand outside the tool, or the registry directory living on NFS where `O_EXCL`
   semantics are weaker — both worth stating in the runbook.
3. **Automation confidence outrunning data quality.** Auto-picking a switch from an inventory
   that is 80% right produces confident wrong answers. Propose-and-confirm is the mitigation,
   and it should stay until the data has earned trust.
4. **Crawling production.** 300 switches on a schedule is real load and real risk of tripping
   something. Needs concurrency limits, and it should be opt-in per site at first.
5. **Scope.** This document describes an inventory-driven provisioning system. The original ask
   was "create configured ports easily". These converge, but the port creation the user asked
   for should not wait for the whole inventory to exist. Hence: LLDP lookup and
   `discover-services` first, both of which deliver value with no inventory at all.
