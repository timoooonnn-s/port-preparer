# Knowledge base

Maintained by the Researcher. Every entry carries a confidence marker:

- **[VERIFIED]** — confirmed on our own hardware or lab, with the command output that proved it.
- **[CITED]** — sourced from Extreme documentation, release notes, or a GTAC article; reference recorded.
- **[ASSUMED]** — expert prior, plausible, **not yet checked**. Never build a safety-critical
  code path on an `[ASSUMED]` entry without the Validator signing off.

Entries are named `NN-topic.md`. When an `[ASSUMED]` becomes `[VERIFIED]`, keep the old
wording in the entry if it was wrong — knowing what we used to believe is useful.

| Entry | Topic | State |
|---|---|---|
| `01-voss-uni-models.md` | The four ways a VOSS port attaches to a service | mostly `[ASSUMED]`, needs lab pass |
