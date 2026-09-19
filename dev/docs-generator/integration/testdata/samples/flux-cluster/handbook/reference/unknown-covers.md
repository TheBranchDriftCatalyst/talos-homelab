---
type: table
status: current
covers:
  - gateway
  - nonesuch
freshness: follows-cluster
tickets:
  - ORCH-108
summary: A covers token that matches no component.
pinned: intentionally lists a bogus token; keep it here rather than beside the gateway.
---

# Component Aliases

EXPECT: covers-resolves

The second `covers:` token above matches no component. The `gateway` token beside it resolves,
which is what makes this a targeted finding rather than a doc that simply has no valid covers
at all.

`pinned:` suppresses the `colocation` finding the resolvable half would otherwise raise.

## Tracking

- ORCH-108 — component aliases
