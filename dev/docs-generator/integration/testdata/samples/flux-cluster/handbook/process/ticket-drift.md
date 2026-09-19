---
type: journal
status: current
covers:
  - path:handbook/process
freshness: frozen
tickets:
  - ORCH-109
  - ORCH-110
summary: A ticket listed in frontmatter but never mentioned in the prose.
---

# Q3 Migration Notes

EXPECTED FINDING: `tickets-in-body` (warn) naming ORCH-110, which appears in the frontmatter
above and nowhere in the prose.

See integration/README.md before trusting that sentence: as shipped, this rule searches the
WHOLE file including the frontmatter it read the ticket from, so it can never fire. This doc is
the evidence, and the spec that covers it asserts the CURRENT behaviour so the day somebody
fixes the rule, the spec fails and says so.

## Tracking

- ORCH-109 — Q3 migration
