---
type: design
status: superseded
covers:
  - storage
freshness: follows-code
tickets:
  - ORCH-105
summary: The original storage layout.
pinned: covers `storage` but documents a decision, not the component; kept with its siblings.
---

# Storage Layout

## Context

EXPECTED FINDING: `frontmatter-schema` (error), `status: superseded requires superseded_by`.

`pinned:` carries a real reason and suppresses the `colocation` finding this doc would
otherwise raise, so the superseded error is the ONLY finding here. That is the pinned-with-a-
reason case.

## Tracking

- ORCH-105 — storage layout v1
