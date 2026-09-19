# Open questions — blocking the first line of code

Raised by the council on 2026-09-19. Owner: the Drafter.
**Bold** questions are blocking; the rest shape the work but can be defaulted.

## A. What the program actually does

- **A1. Generate or apply?** Does the tool render config for a human to paste, or does it log
  into the switch and push? Recommendation: both, with `--dry-run` as the default and `--apply`
  explicit.
- **A2. Save config?** After a successful apply, does it `save config`, and does it take a
  `show running-config` backup first? (Recommendation: backup always, save only on `--save`.)
- **A3. Who runs it?** Each engineer from their own shell on the Linux hosts, or one central
  automation host / CI runner?
- **A4. Interface shape?** Interactive wizard, YAML/CSV batch for bulk builds, or both?
  Appetite for a web UI later?
- **A5. Change record?** Does the tool need to emit something a human reviews or attaches to a
  ticket before apply?

## B. The Fabric Connect model — the biggest fork

- **B1. Which UNI model for DC server access: Switched UNI (flex-uni) or platform VLAN +
  I-SID?** See `knowledge-base/01-voss-uni-models.md`. If both exist in the field, is there a
  rule (new builds one way, legacy the other)?
- **B2. T-UNI (`elan-transparent`) anywhere?**
- **B3. Is auto-sense enabled on the 9.4.1 boxes?** If yes, the tool must take a port away from
  auto-sense deliberately and refuse ports it does not own.
- **B4. Fabric Attach** — do we provision FA proxy/server ports, and must the tool touch FA?
- **B5. I-SID numbering scheme** — deterministic from VLAN (e.g. `1000000 + vid`) or free-form?
  Where does the allocation truth live, and does the tool allocate or only consume?
- **B6.** Is a given service the same VLAN ID everywhere, or are C-VIDs locally significant?
- **B7.** L3 VSN / VRF / `ipvpn` — out of scope for v1? (Assumed yes.)
- **B8.** Multicast over Fabric Connect on these UNIs (`ip spb-multicast enable`)?

## C. Redundancy

- **C1. Dual-homed servers on SMLT/vIST pairs?** If so the tool must configure both peers as
  one transaction, which changes the whole execution model (and the failure model: peer 1
  succeeded, peer 2 did not).
- **C2.** MLT-ID and LACP-key allocation — who owns the number space?
- **C3.** Static MLT anywhere, or LACP only?

## D. The gold standard — what "configured correctly" means

- **D1. Sanitised `show running-config` excerpt of one known-good port per scenario**, including
  the VLAN/I-SID lines it depends on. This is the highest-value artifact the user can provide;
  it replaces a week of guessing.
- **D2.** Mandatory hygiene on access ports — which of these are policy: MSTP edge /
  `force-port-state`, BPDU guard, SLPP guard + timeout, `extended-cp-limit`, `loop-detect`,
  broadcast/multicast rate-limit, VLACP, QoS level and `access-diffserv`, EAPoL/802.1X,
  PoE, MACsec, `link-flap-detect`?
- **D3.** Port `name`/description convention — does it encode host, rack, ticket?
- **D4.** MTU / jumbo frames on DC ports?

## E. Inventory and targeting

- **E1.** Where does the device list live? NetBox / Nautobot / XIQ-SE / Fabric Manager / CSV /
  Ansible inventory / nothing?
- **E2.** "Management ports only on specific switches" — how does the tool *know* which
  switches qualify? Role tag, hostname pattern, site, explicit allow-list?
- **E3.** Scale: how many switches, sites, and separate fabrics/ISIS areas?
- **E4. Is there a lab, spare VSP, or VOSS VM to test against?** If not, the Validator builds a
  mock-transport plus golden-file harness instead, and that needs planning now.

## F. Access and credentials

- **F1.** SSH CLI only, or is REST/RESTCONF enabled? (Recommendation: netmiko `extreme_vsp`
  over SSH, for consistency across 8.x and 9.4.1.)
- **F2.** Auth model: TACACS+/RADIUS per-engineer, shared service account, SSH keys?
- **F3.** Where do credentials come from — prompt, ssh-agent, Vault, env, `.netrc`?
- **F4.** Direct reachability from the Linux hosts, or via bastion/ProxyJump?
- **F5.** Is `--apply` allowed for everyone, or gated?
- **F6.** Audit requirement — central syslog of every change, and in what format?

## G. Stack

- **G1.** Python version on the Linux hosts, and may we use a venv / install packages?
- **G2.** Ansible as the executor, or pure Python? (Recommendation: Python core library + CLI
  as the product; the existing `community.network.voss_*` modules are thin and Ansible makes
  interactive use and rich diffs harder.)
- **G3.** Should rendered intent be committed to git as the record of truth (declarative,
  heading toward an intended-state engine), or is this imperative fire-and-forget tooling?

## H. Versions

- **H1.** Exact VOSS versions and platform models in the field. The tool wants a
  version-gated capability matrix, not a lowest-common-denominator guess.
- **H2.** Non-VOSS gear these ports touch (EXOS, ERS 4900/5520) — eventual scope or never?

## I. Scope of v1 — confirm

- **I1.** Is *decommission a port* in v1? (Council recommends yes, second priority: same data
  model, and it is the riskier operation done by hand today.)
- **I2.** Is *audit an existing port against its template* in v1? (Council recommends yes, and
  **first** — read-only, zero blast radius, and it proves the data model against reality before
  we ever write to a switch.)
