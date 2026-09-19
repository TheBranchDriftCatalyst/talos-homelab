---
type: howto
status: current
covers:
  - catalog
freshness: live
tickets:
  - PD-05
summary: The one note in this sample that carries a summary, so the nav table has exactly one non-fallback description.
---

# Deploying

## Steps

1. Build the image.
2. Push it.

EXPECT: colocation

Covers `catalog`, whose path is `services/catalog`, but lives in `notes/`. No `pinned:` key, so
nothing suppresses it.

## Follow-up

- PD-05 — deploy howto
