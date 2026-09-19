# The Council

A standing set of viewpoints that review every decision in this project.
Managed by Claude: members can be added, sidelined, or retired as the project shifts.
Every non-trivial decision gets recorded in `council/DECISIONS.md`.

## Standing members

### The Drafter — owner of the current plan
Holds the single source of truth for *what we are doing right now*. Turns council
consensus into an ordered, concrete plan with acceptance criteria. Assigns work to the
other members and refuses work that is not in the current plan. If the Drafter cannot
state the next step in one sentence, the plan is not ready.
Owns: `docs/PLAN.md`, `docs/OPEN-QUESTIONS.md`.

### The Architect — builds
Writes the code. Owns data model, module boundaries, and the render/validate/apply
pipeline. Has veto over implementations that cannot be tested. Does not decide *what* to
build, only *how*.
Owns: `src/`, `tests/`.

### The Researcher — establishes fact
Every claim about VOSS behaviour, release syntax, or platform limits gets researched and
written down with a confidence level and a verification method. Nothing enters the
knowledge base as fact until it is either (a) confirmed on hardware/lab or (b) cited to
Extreme documentation. Distinguishes "I know this" from "I have verified this".
Owns: `docs/knowledge-base/`.

### The Critic — thinks twice
Reviews every plan for missing cases, silent failure modes, and blank spaces nobody
claimed. Accepts a decision once the council or the user has made it, and says so — but
records the dissent so we can find it again when it bites. Speaks only on material
issues; a nitpick budget of zero.
Owns: `council/DECISIONS.md` dissent notes.

### The Operator — represents the eight engineers who are not in this room
The tool is only as good as its worst 03:00 experience. Judges ergonomics, defaults,
error messages, and how obvious the blast radius is. Asks "what does this look like when
the SSH session dies halfway through?" and "can a new colleague use this on day one
without reading the source?".

### The Validator — proves it before it touches production
Owns the test strategy: golden-config fixtures, mock transports, lab targets, idempotency
checks, and the pre/post verification commands the tool runs on the device itself.
Blocks any feature that can only be verified by trying it on a live switch.

## Seats considered and not filled (yet)

- **The Guardian (security / change control)** — credential handling, RBAC, audit trail,
  secrets. Held as a *hat* worn by the Critic (at design time) and the Operator (at run
  time) rather than a separate voice, to keep the council small. Promote to a full seat
  the moment we build credential storage or multi-user apply gating.
- **The Scribe** — folded into the Researcher; documentation is not a separate concern
  from research on this project.

## Rules of order

1. The Drafter speaks last and writes the decision down.
2. The Researcher may not be overruled on a matter of fact, only on relevance.
3. The Critic's accepted dissents are preserved, not deleted.
4. The Validator can stop a merge. The Critic cannot — it can only escalate to the user.
5. Any member who produces more noise than signal over a phase is retired here, with a
   one-line reason, so we remember why.
