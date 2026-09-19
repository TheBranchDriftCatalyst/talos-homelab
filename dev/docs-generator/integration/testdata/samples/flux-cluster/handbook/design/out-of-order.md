---
status: current
type: design
covers:
  - path:handbook/design
freshness: follows-code
tickets:
  - ORCH-114
summary: Keys in the wrong order.
---

# Retry Policy

## Context

EXPECT: frontmatter-schema

The first two keys above are swapped. The canonical order the message reports is this sample's
`key_order`, not talos-homelab's — it names `summary` where the real repo names `blurb`, which
is how this doc pins that `key_order` is config-driven.

## Tracking

- ORCH-114 — retry policy
