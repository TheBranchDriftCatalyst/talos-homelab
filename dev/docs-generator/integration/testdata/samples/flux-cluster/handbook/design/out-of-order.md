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

EXPECTED FINDING: `frontmatter-schema` (error), `type` should come before `status`. The
reported canonical order is this sample's `key_order`, not talos-homelab's — the message names
`summary` where the real repo names `blurb`, which is how this doc pins that `key_order` is
config-driven.

## Tracking

- ORCH-114 — retry policy
