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
