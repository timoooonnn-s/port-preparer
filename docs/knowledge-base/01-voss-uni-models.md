# 01 — VOSS UNI models: the four ways a port attaches to a service

**Status:** drafted from expert prior on 2026-09-19. Almost everything here is `[ASSUMED]`
until run against our own 8.x and 9.4.1 boxes. Syntax below is written from memory of the
VOSS CLI and **must not be shipped into the tool's templates before a lab pass.**

This is the single most important distinction in the whole project, because the tool's data
model is different for each one. The Drafter has made this question #1 for the user.

---

## A. Platform VLAN with I-SID ("CVLAN UNI", the classic model) `[ASSUMED]`

A normal port-based VLAN exists on the switch and is mapped to an I-SID, which extends it
across the fabric as an L2 VSN.

```
vlan create 100 type port-mstprstp 0
vlan i-sid 100 1000100
vlan members add 100 1/1 portmember
interface gigabitEthernet 1/1
    encapsulation dot1q        # tagged; omit for untagged
    name "srv-esx01-vmnic0"
exit
```

- Pros: familiar, shows up in `show vlan basic`, easy to reason about, works everywhere.
- Cons: consumes a platform VLAN per service per switch; VLAN-ID space becomes a
  fabric-wide coordination problem; scaling ceiling on VLAN count.

## B. Switched UNI / Flex UNI `[ASSUMED]`

No platform VLAN. The port is put into flex-UNI mode and C-VIDs are bound directly to
I-SIDs, so the VLAN ID becomes *locally significant*.

```
interface gigabitEthernet 1/1
    flex-uni enable
exit
i-sid 1000100 elan
    c-vid 100 port 1/1              # tagged
    untagged-traffic port 1/1       # untagged
exit
```

- Pros: no platform-VLAN consumption, C-VID reuse per port, scales far better, the natural
  fit for DC server access where each host wants different tags.
- Cons: different mental model, `show vlan` no longer tells the whole story,
  **and a flex-UNI port cannot also be a member of platform VLANs** — this constraint is
  the reason the two models cannot be casually mixed on one port. `[ASSUMED — verify per
  release, this is the claim most likely to be subtly wrong]`

## C. Transparent Port UNI (T-UNI, `elan-transparent`) `[ASSUMED]`

The entire port, tag-agnostic, is dropped into one I-SID. Everything in, everything out.

```
i-sid 1000200 elan-transparent
    port 1/2
exit
interface gigabitEthernet 1/2
    no spanning-tree mstp
exit
```

- Port must be removed from all VLANs first, and spanning tree disabled on it. `[ASSUMED]`
- Use case: handing a whole physical port to a tenant or to a transparent transport.
- Danger: no VLAN filtering whatsoever. A T-UNI port is a loop waiting for an opportunity;
  the Critic wants loop protection treated as mandatory here, not optional.

## D. Auto-sense `[ASSUMED]`

VOSS 8.3+ can detect what is plugged in (ISIS neighbour / Fabric Attach proxy / plain host)
and configure the port itself, including an onboarding I-SID.

```
interface gigabitEthernet 1/3
    auto-sense enable
exit
```

**Open conflict:** if auto-sense is enabled on the boxes, it and this tool are two control
planes fighting over the same port. The tool almost certainly needs to explicitly
`no auto-sense enable` on any port it takes ownership of, and needs to *detect and refuse*
a port currently auto-sensed into a service. Escalated to the user as question B3.

---

## Cross-cutting facts to verify in the same lab pass

1. Whether `flex-uni enable` and platform-VLAN membership are truly mutually exclusive, per
   release (8.4 / 8.6 / 8.10 / 9.4.1).
2. Order of operations: does the I-SID have to exist before the `c-vid ... port` binding, and
   what is the error if not?
3. Whether the port must be `shutdown` for any of these transitions, and which ones bounce
   traffic.
4. What happens to an existing service when the model is changed on a live port — the
   decommission/convert path, which is where hand-work currently hurts most.
5. Exact behaviour of `untagged-frames-discard` and `default-vlan-id` in each model.
6. On an SMLT pair: which of the above must be identical on both vIST peers, and which is
   allowed to differ. `[ASSUMED: I-SID and C-VID binding must match exactly; MLT/SMLT id must
   match; port numbers may differ]`
