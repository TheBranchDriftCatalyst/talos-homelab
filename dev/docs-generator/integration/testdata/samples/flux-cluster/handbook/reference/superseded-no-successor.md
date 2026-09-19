---
type: table
status: superseded
covers:
  - path:handbook/reference
freshness: follows-cluster
tickets:
  - ORCH-107
summary: A superseded table that names no successor, so the nav must not list it.
---

# Retired Quota Table

EXPECT: frontmatter-schema

`status: superseded` with no `superseded_by` is a dead end: it says "do not trust me" and offers
nowhere to go. The nav must skip it, and the schema rule must still report the missing key.

## Tracking

- ORCH-107 — reference tables
