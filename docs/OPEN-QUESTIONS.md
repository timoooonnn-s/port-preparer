# Open questions

Revised 2026-09-19. The first round is answered; this is what remains.
Owner: the Drafter.

## Answered — recorded in `PLAN.md`

A1–A5, B1–B8, C1, E1–E4, F1–F6, G1–G3, H1–H2, I1–I2 are settled. Three answers were
superseded by better evidence than prose:

- **B1 ("both exist, hard call to give you a rule")** — resolved without a rule. `show i-sid`
  reports `TYPE = ELAN` vs `CVLAN`, so the engine detects the model instead of assuming it.
- **B6 ("I think so, not sure")** — largely moot for the same reason.
- **D1/D2 ("can't do that currently, start with the engine")** — the fixtures in
  `switch-migrator` turned out to contain exactly the gold-standard config we were asking
  for, including a real flex-uni access port. Question closed by evidence.

## Still blocking — but only for *proposing* values, not for the audit milestone

Phase 0 and Phase 1 proceed without these. They bite at Phase 2, when the engine has to
suggest an I-SID or an MLT id rather than validate one the engineer typed.

- **Q1. MLT id allocation.** You said `4xx` where `xx` is the port id. `show mlt` on
  `gx-11-s72-p1` shows ids 1, 35, 38, 196–200, with the port encoded in the *name*
  (`f110` = 1/10, `f143` = 1/43, `s129` = 1/29) and not in the id. Is `4xx` a newer convention,
  another site, or another platform? And what do the name prefixes `f`, `s`, `svi` mean?
- **Q2. I-SID prefix selection.** The `<prefix><4-digit vlan>` shape is confirmed, but 250 and
  251 coexist on one switch with no derivable pattern (695→250 but 696→251). What picks the
  prefix, and what do 270 / 271 / 299 mean? Also: is `1531100` for the vIST VLAN a separate
  infrastructure scheme?
- **Q3. VLAN name letter.** The format `<LETTER><12-digit network><_prefixlen>` decodes
  perfectly (`E010035016000_21` = 10.35.16.0/21). What do `E`, `X` and `R` distinguish?
  If the tool knows, it can generate names and flag mismatched ones for free.

## Newly raised by the fixture review

- **Q4. Is DVR deployed?** `boot config flags dvr-leaf-mode` is set in the captured
  running-config and `show dvr interfaces` returns rows. Nobody mentioned DVR. Which sites,
  and are DC access switches DVR leaves? DVR leaf restrictions are a class of failure that
  only surfaces at apply time.
- **Q5. One real T-UNI example.** You think `elan-transparent` exists in the estate, but no
  fixture contains one. Until we see real output the engine will parse and report T-UNI but
  refuse to create it.
- **Q6. A sample IPAM export.** One sanitised CSV with the real headers, even five rows, lets
  the inventory loader be built against reality instead of a guess.
- **Q7. May I vendor the `switch-migrator` fixtures into this repo** (`tests/fixtures/`) so the
  parser tests are self-contained and do not depend on a branch in another repository?
- **Q8. Lab access.** You have a lab, but this session cannot reach your network. Do you want
  to run a verification script I produce and paste the output back, or should I assume the
  lab pass happens on your side against a checklist? The seven items in KB entry 01 are the
  list.
- **Q9. Per-site-category deltas.** "Each category uses a slightly different config." I can
  build the inheritance mechanism without the values, and will. When you want real profiles
  for DC / large office / branch, one example config per category is what unblocks it.


  ## User questions
  - **01.** Option to automate "the which switch decision". Spike the inventory with exact rack naming of each device. Input some facts about the server or end-device (for server, pre categorize into linux, windows or esx (and more if needed, examples, not complete list)
When a new port should get provided, the tool should automatically decide where the nearest free switch with available ports is
- **02.** Phasings: Currently, there is a Config A, which gets done on the port for the linux and windows admin, that they can configure their server. When they are finished, the final config for the application gets deployed on the port. I would like to simplify this process - don't really get why this is done in "two steps".. 


## Deliberately deferred

L3 VSN / VRF / `ipvpn`, multicast over Fabric Connect, Fabric Attach, REST transport,
EXOS/ERS. All noted in the design so they are additions rather than rewrites.
