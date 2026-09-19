---
type: architecture
status: current
covers:
  - path:handbook/design
freshness: follows-code
tickets:
  - ORCH-117
summary: A type from somebody else's vocabulary.
---

# Queue Topology

EXPECTED FINDING: `frontmatter-schema` (error), `type architecture not in [...]`.

`architecture` is talos-homelab's word; this repo's word is `design`. The finding is the
evidence that `doc_types` really is read from config. Note also what does NOT happen: because
`architecture` has no `type_requires` entry here, no `## Context` section is demanded, so this
doc raises exactly one finding.

## Tracking

- ORCH-117 — queue topology
