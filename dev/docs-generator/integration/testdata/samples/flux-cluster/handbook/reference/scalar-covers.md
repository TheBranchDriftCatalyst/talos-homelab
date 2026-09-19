---
type: table
status: current
covers: gateway
freshness: follows-cluster
tickets:
  - ORCH-118
summary: covers written as a scalar rather than a block sequence.
pinned: shape test; belongs with the other reference-table fixtures.
---

# Gateway Routes

EXPECT: frontmatter-schema

`covers:` above is written as a scalar rather than a block sequence.

A scalar still RESOLVES — the tool coerces it — so this is a shape complaint, not a broken
reference. It matters because prettier explodes a flow sequence, which would make any generated
file carrying one stop being a prettier fixed point.

## Tracking

- ORCH-118 — gateway routes
