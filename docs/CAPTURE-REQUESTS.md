# What we need from the lab

The tool has a `capture` subcommand precisely for this. Run it, sanitise, commit — that is
the whole loop, and it is the only way output we have never seen reaches the test suite.

```sh
port-preparer capture --host <switch> --output captures/<switch>
```

Then, before committing: **replace hostnames with strings of the same length.** Several tables
(`show lldp neighbor summary`, `show vlan members`) are parsed by column offset, so a shorter
substitute shifts the columns and corrupts the fixture. This has already bitten us once.

## Ranked by how much it unblocks

### 1. A T-UNI port — blocks generating T-UNI at all
No capture we have contains an `elan-transparent` I-SID. Until one does, the engine reports
T-UNI but refuses to create it. Wanted:

```
show i-sid
show interfaces gigabitethernet i-sid
show running-config          # the i-sid <x> elan-transparent block and the port's own config
```

### 2. A management switch (`m*`) — blocks the management scenario
We have no sample of one. A full `capture` run against any `m*` switch, plus a note on how the
management VLAN and I-SID are meant to look on a correct management port.

### 3. A 9.4 box — blocks release gating
Every capture we have is 8.10.9.0 or a doc-derived reconstruction. The version-gated
capability matrix is currently a plan, not data. A full `capture` from one 9.4 switch, and
one 9.1 or 9.3 if they differ.

### 4. One correct port per scenario, per site category
You said each of DC / large office / branch uses a slightly different config. The profile
inheritance mechanism is built; the values are empty. One known-good port's config per
combination fills it in. This is the artifact that turns the provisional profile in
`src/port_preparer/profiles/default.yaml` into policy.

### 5. A dual-homed server on an SMLT pair — blocks Phase 4
Captures from **both** vIST peers for the same server, so we can see exactly which lines must
match and which may differ. Wanted from each peer:

```
show mlt
show virtual-ist
show i-sid
show running-config
```

### 6. A sanitised IPAM export
Five rows with the real headers is enough to build the inventory loader against reality rather
than a guess.

## Behaviour to confirm on the box

These are the `[ASSUMED]` items in `knowledge-base/01-voss-uni-models.md`. Each is a claim the
generator would rely on, and none is verified.

1. Does `encapsulation dot1q` in the *same* interface block as `flex-uni enable` actually
   fail? Real config emits them in two separate blocks (PHASE I / PHASE II) and the generator
   copies that; we would like to know whether it must.
2. Are `flex-uni enable` and platform-VLAN membership genuinely mutually exclusive, on 8.10
   and on 9.4?
3. Must the I-SID exist before its `c-vid <n> port <p>` binding, and what is the error text
   when it does not?
4. Which of these transitions bounce traffic, and does the port need shutting down first?
5. What happens to a live service when the UNI model is changed underneath it — the convert
   path, which is where hand-work hurts most today.
6. On an SMLT pair: which lines must match exactly on both peers?
7. Does the MLT-id `4xx` rule apply to channelized sub-ports (`2/1/1`)? The convention encodes
   a two-part id; three-part ids currently raise and demand an explicit id.

## Open questions that are not captures

Q1 (MLT ids: `4xx` vs the 196–200 on the captured switch, and what `f`/`s`/`svi` mean in MLT
names) and Q3 (what `E`, `X`, `R` mean in VLAN names) need an answer from a person, not a
switch. Both are recorded in `OPEN-QUESTIONS.md`.
