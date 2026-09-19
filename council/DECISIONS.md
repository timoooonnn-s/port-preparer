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
