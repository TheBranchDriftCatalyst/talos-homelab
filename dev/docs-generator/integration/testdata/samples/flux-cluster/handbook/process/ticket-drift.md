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

EXPECT: tickets-in-body

The SECOND ticket in the frontmatter above appears there and nowhere in this prose. The first is
cited under Tracking below, so exactly one finding is expected, not two.

DO NOT WRITE THAT TICKET ID ANYWHERE IN THIS BODY — not even to explain what this file is for.
The rule is a substring search over the body, so naming the ticket here silently repairs the
document and the spec then passes while testing nothing. That is not hypothetical: this file
did exactly that until 2026-09-19, and `missing-footer.md` in the sibling sample did the same
with its footer heading. A fixture that describes its own defect tends to cure it. The
declaration above names only the rule, so there is nowhere in it for the ticket id to appear.

## Tracking

- ORCH-109 — Q3 migration
