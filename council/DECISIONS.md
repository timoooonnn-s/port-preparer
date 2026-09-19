# Decision log

Format: date, decision, who pushed for it, recorded dissent, and how we would know it was
wrong.

## 0001 — Council formed, six seats
**Date:** 2026-09-19
**Decision:** Drafter, Architect, Researcher, Critic (given by the user) plus Operator and
Validator. Security/change-control handled as a hat rather than a seat for now.
**Dissent (Critic):** A project whose failure mode is "we pushed bad config into a
production Fabric Connect core" arguably deserves a dedicated Guardian from day one. I
accept the small-council decision, and I want it revisited the moment we write code that
stores a credential or decides who is allowed to apply.
**Falsified if:** credential handling or apply-authorisation design starts leaking into
three different files because nobody owns it.

## 0002 — No code until the profile is known
**Date:** 2026-09-19
**Decision:** Nothing is implemented before the user answers the blocking questions in
`docs/OPEN-QUESTIONS.md`. The biggest fork (Switched UNI vs. platform-VLAN UNI) changes
the core data model, so building now means building twice.
**Dissent (Architect):** I could scaffold the transport and CLI layers now; they are
independent of the UNI model. Accepted as a compromise: scaffolding is allowed once the
delivery-mode question (generate vs. apply) is answered, which is the only one those
layers depend on.
**Falsified if:** the answers arrive and turn out to leave the data model untouched.

## 0003 — Detect the UNI model, never assume it
**Date:** 2026-09-19
**Decision:** The user could not state a rule for Switched UNI vs platform VLAN. The engine
will not need one: `show i-sid` reports `TYPE = ELAN` (switched UNI) or `CVLAN` (platform
VLAN), so the tool reads the switch and follows whatever that switch already speaks.
**Pushed by:** the Researcher, from `voss/show_i_sid.txt`.
**Dissent:** none. The Critic notes this converts the project's biggest unknown into a parser
requirement, which is a good trade.
**Falsified if:** a switch is found running both models in a way that makes "what does this
port speak" ambiguous, or if a release prints the TYPE column differently.

## 0004 — A port holds a list of bindings, not a tagging mode
**Date:** 2026-09-19
**Decision:** Core data model is `Port -> [Binding(i_sid, c_vid | untagged)]`.
**Pushed by:** the Architect, from the real running-config where port 1/4 carries I-SID
2500695 as both `c-vid 695` and `untagged-traffic`, plus I-SID 2510735 as `c-vid 735`.
**Dissent:** none. This retires the user's "sometimes with and sometimes without VLAN
tagging" as a per-port question — it is per binding.
**Falsified if:** a platform-VLAN-model port cannot be expressed in the same shape, forcing
two parallel models.

## 0005 — Templates are data, not code
**Date:** 2026-09-19
**Decision:** Scenarios and site profiles live in YAML with an inheritance chain
(global → site-category → site → device-role → scenario → port override). Adding a scenario
must never require editing Python.
**Pushed by:** the Operator. "Three scenarios named means three scenarios today."
**Dissent (Architect):** unbounded data-driven templating becomes a second, worse programming
language. Accepted with a limit: profiles may set values and toggles, and may not contain
conditionals or expressions. Anything needing logic gets a named capability in code.
**Falsified if:** the first genuinely new scenario still requires a code change.

## 0006 — Build Phase 0 and 1 while Q1–Q3 are open
**Date:** 2026-09-19
**Decision:** The skeleton and the read-only audit depend on none of the open questions. Build
them now; the numbering rules are only needed to *propose* an I-SID or MLT id, which is
Phase 2.
**Pushed by:** the Drafter.
**Dissent (Critic):** recorded and accepted — if Q2 comes back as "the prefix means which
fabric the service belongs to", that is inventory data, and inventory is Phase 1. Watch for it.

## 0007 — Severity distinguishes legacy from wrong
**Date:** 2026-09-19
**Decision:** Findings are graded error / warning / legacy / unknown / info. A port or object
that does not follow a convention introduced after it was built is `legacy`, and `legacy` never
fails an audit.
**Pushed by:** the Operator, after the user said the fixtures are older than the rules.
**Dissent (Critic):** "legacy" is a category that will be used to bury real problems. Accepted
with a condition: `legacy` is only for a *known* convention change, never for something we
merely do not understand. Anything we do not understand is `unknown`.
**Falsified if:** a real defect is found sitting in the legacy bucket.

## 0008 — Absence of evidence is never reported as absence of configuration
**Date:** 2026-09-19
**Decision:** `uni_model` returns `UNKNOWN`, not `UNUSED`, when the collection did not include
the commands that would reveal a service. The production capture we have lacks
`show vlan members`, and an earlier build reported all 54 of its ports as free.
**Pushed by:** the Critic, having found exactly that in the first discovery run.
**Dissent:** none. The Operator notes this is the difference between a tool engineers trust and
one that patches over a live server.
**Falsified if:** the UNKNOWN state is so common in practice that people learn to ignore it --
in which case the fix is to collect more, not to guess.

## 0009 — `capture` is a first-class command, not a debug aid
**Date:** 2026-09-19
**Decision:** The tool writes raw show output in the exact layout the test suite reads.
**Pushed by:** the Validator. The user runs the tool in the lab and reports back, so this is the
only route by which output we have never seen (T-UNI, 9.4, management switches) reaches a test.
Captures must be sanitised with **equal-length** substitutions, because several tables are
parsed by column offset.
**Dissent:** none. Learned the hard way: the first sanitisation pass shortened hostnames and
silently corrupted the LLDP fixture.

## 0010 — I-SID prefix encodes the environment
**Date:** 2026-09-19
**Decision:** `250`/`251` prod, `270`/`271` non-prod, `299` special. Within an environment the
two variants were "the engineer's mood" and are treated as equivalent; the tool generates the
canonical lower one and grades the other `legacy`. Infrastructure I-SIDs are never generated.
**Pushed by:** the user, answering Q2. This is what unblocked *proposing* an I-SID.
**Dissent (Critic):** we accepted "mood" as the explanation for 250-vs-251 without proving it.
If the second variant turns out to mean something (a second fabric, a migration wave), the tool
will canonicalise away real information. Cheap mitigation taken: the variant is reported, not
silently rewritten, wherever it already exists.
**Falsified if:** two services in the same environment are found needing different prefixes.

## 0011a — The registry is per-object files in git, on the one automation host
**Date:** 2026-09-20
**Decision:** No NetBox — the user states it is not obtainable, so it is a boundary rather than a
later phase. The registry is one small YAML file per allocated object under `registry/`, held in
git. Allocation is `O_CREAT|O_EXCL` on the object's own path, which is atomic; multi-step
operations take a `flock`. Device inventory arrives as CSV, because that is how the IPAM export
arrives.
**Pushed by:** the user, ruling NetBox out. The Architect notes this turns the allocation race
from "a database will fix it" into a solved problem, which is a better outcome: per-object files
also remove git merge conflicts, which one shared registry file would have guaranteed.
**Dissent (Critic):** `O_EXCL` is only as atomic as the filesystem underneath it. If
`registry/` ever lands on NFS this guarantee quietly weakens, and nothing in the tool would
notice. Accepted with a condition: the runbook states the registry must live on local disk on the
automation host, and the tool warns if it can detect otherwise.
**Also recorded:** a thin `Registry`/`Inventory` seam is kept so the store could be replaced, but
it is a seam, not a plugin system. We are not building for a backend that is not coming.
**Falsified if:** hand-editing outside the tool turns out to be common enough that atomicity at
the file level buys nothing.

## 0011 — PROPOSED: a registry, not a statefile
**Date:** 2026-09-20
**Status:** proposed, awaiting the user. Nothing is built on it yet.
**Decision:** The persistent store holds only what a device cannot report — allocations, service
intent, ownership, physical facts, lifecycle position. Reality is re-read from the device every
time and never cached as authority. The tool must never refuse to act because its registry
disagrees with a device: the device wins, the registry is corrected, the discrepancy is a
finding.
**Pushed by:** the Architect, from the observation that Terraform state exists mostly to map
logical names to opaque cloud ids and to avoid API calls, and neither problem exists here.
**Dissent (Critic):** re-reading a device every time is slower and assumes the device is always
reachable; there will be a moment when someone wants a cached answer for a report across 300
switches. Accepted with a condition: caching is allowed for *reporting* and must carry an
explicit "as of" timestamp, but the apply path always reads live.
**Also recorded (Critic):** we are calling the store a "registry" specifically to keep the
Terraform mental model out of the design. If people start calling it state, expect the
"refresh required" failure mode to follow.
**Falsified if:** a real need appears to diff against something other than the live device.

## 0012 — PROPOSED: propose-and-confirm, not auto-pick
**Date:** 2026-09-20
**Status:** proposed.
**Decision:** Switch and port selection outputs the top three candidates with reasoning and
disqualifications; the engineer confirms. Full autonomy is deferred until the proposals have
been right for long enough to trust.
**Pushed by:** the Operator. A wrong automatic pick costs a walk to the wrong rack, or a patch
into a live port.
**Dissent (Drafter):** the user explicitly asked for the tool to "decide by itself", so this is
a narrowing of the stated ask and must be presented as such rather than quietly implemented.
Accepted: it is being put to the user as a decision, not assumed.
**Falsified if:** the proposals prove so consistently right that confirmation is pure friction.

## 0013 — REVISED: locate already-cabled devices by MAC, not by LLDP name
**Date:** 2026-09-20 (proposed), revised the same day.
**Status:** the split stands; the mechanism changed before anything was built.
**Original decision:** find an already-racked server's port via LLDP, which names the switch and
port and needs no inventory.
**Why it was wrong:** the user warned from migration experience that LLDP data is inconsistent or
absent. Measuring their own capture: every one of the 7 switch-to-switch links advertises a
sysname, and **none of the 8 servers does**. Two rows are additionally truncated by the CLI. So
looking a server up by name over LLDP cannot work here at all.
**Revised decision:** the locator keys on **MAC address**, supplied by the requester, matched
against the forwarding database. LLDP chassis id corroborates; link state plus a fitted optic is
an absolute negative check. The locator reports a confidence and treats *not found* and
*ambiguous* as first-class outcomes. It is blocked on a real FDB capture and will not be trusted
before one exists.
**Pushed by:** the user, correcting the council.
**Dissent (Critic):** I should have caught this from the fixture, which was already in the repo
and already showed eight nameless servers. The lesson is not about LLDP: it is that "the data is
present" and "the data is usable for the thing I want" are different claims, and I checked the
first and asserted the second.
**Standing rule added:** absence of LLDP is never evidence that nothing is plugged in — the same
class of error as decision 0008.
**Falsified if:** the FDB turns out to be as patchy as LLDP, in which case device location is an
inventory problem only and there is no shortcut.
