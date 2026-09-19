# 03 — Identifying which port a device is on

**Written 2026-09-20** after the user warned that LLDP data in their estate is inconsistent or
sometimes absent, from experience during a switch migration. The council measured it against
their own production capture, and the warning is correct — more sharply than expected.

## The measurement `[VERIFIED-FIXTURE]`

On `sw-aa-s01-p1` (VSP-7254XSQ, 8.10.9.0), 15 ports have link up and all 15 have an LLDP row.
But splitting those rows by what is on the far end:

| Far end | Rows | Have a `SYSNAME`? |
|---|---|---|
| Other switches (1/1, 1/2, 1/8, 1/16, 1/23, 1/24, 1/29) | 7 | **7 of 7** |
| Servers (1/7, 1/10, 1/13, 1/14, 1/15, 1/43, 1/45, 1/46) | 8 | **0 of 8** |

Every switch-to-switch link identifies itself properly. **Not one server does.** What a server
row actually contains:

```
1/7    sysname=None   remote_port='Embedded ALOM, Po~'  descr='ProLiant DL380 Gen10'
1/10   sysname=None   remote_port='3c:a8:2a:00:00:0a'   descr='HPE ProLiant DL580 Gen10'
1/13   sysname=None   remote_port='3c:a8:2a:00:00:0d'   descr='HPE ProLiant DL380 Gen10'
```

Two further rows (1/7, 1/29) are **truncated by the CLI itself** — trailing `~` where the
column ran out. So even the fields that are present cannot always be read in full.

## What this kills, and what it leaves

**Killed: looking up a port by device name.** The council proposed "tell me the server and I
will find its port via LLDP". In this estate that cannot work, because servers do not advertise
a name. This was proposed as decision 0013 and is being revised rather than built.

**Left standing:** LLDP is genuinely reliable for *infrastructure* — uplinks, vIST peers, ring
and stack links all name themselves. Keep using it for topology. And for servers it still yields
two useful facts: a **chassis MAC** and a **hardware model string**.

So the lookup key cannot be a hostname. It has to be a **MAC address**, supplied by whoever
requests the port (build ticket, IPAM, the OS team).

Caveat on that MAC: the LLDP chassis id on a ProLiant is typically the **iLO/ALOM** management
processor, not the data NIC. So the MAC in LLDP and the MAC in the forwarding database may be
different addresses on the same physical machine. Do not assume they match.

## Signals, ranked

| Signal | Reliability | Needs |
|---|---|---|
| **Forwarding database** (`show vlan mac-address-entry`, and the I-SID equivalent for switched UNI) | **Best.** Requires no cooperation from the endpoint — only that it has sent a frame | the device's MAC, and a port already forwarding in some VLAN/I-SID |
| **Link state + transceiver** | **Absolute, for the negative case.** Optic fitted and link up means something is there, whatever LLDP says | nothing |
| **ARP/ND on the DVR gateway**, then MAC→port | Good, two hops | the device's IP |
| **LLDP chassis id + model** | Partial. Present here for every linked server, but carries no name | nothing |
| **Port statistics** — a port that has never passed a frame is genuinely unused | Useful corroboration | one more command |
| **LLDP sysname** | **Unusable for servers in this estate** | — |
| Port name/description | Unusable — access ports are not named here by convention | — |

## Design consequences

1. **The locator must combine signals and report a confidence, never do a single-source
   lookup.** Outcomes must include *not found*, *ambiguous*, and *several candidates* as
   first-class answers, not as errors.
2. **Absence of LLDP must never be read as "nothing is plugged in."** This is the same class of
   mistake as reporting an uncollected port as free — see decision 0008. Link up plus an optic
   fitted means occupied, full stop.
3. The FDB commands are **`[ASSUMED]`**: we have no capture of `show vlan mac-address-entry` or
   its I-SID counterpart, and the exact syntax differs between the platform-VLAN and switched-UNI
   models. Added to `CAPTURE-REQUESTS.md`. Nothing MAC-based should be trusted until we have real
   output.
4. `discover-services` is **unaffected** by all of this. It harvests I-SIDs, VLANs and bindings,
   none of which depend on LLDP. It stays the next thing to build.
