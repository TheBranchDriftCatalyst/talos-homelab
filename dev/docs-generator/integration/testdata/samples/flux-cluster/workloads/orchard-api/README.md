---
type: design
status: current
covers:
  - orchard-api
freshness: follows-code
tickets:
  - ORCH-115
summary: The Orchard API service.
---

# Orchard API

## Context

EXPECT: none

Deployed after the gateway; `orchard-web` in turn depends on this. That three-level chain is
declared in the Kustomizations and is, today, read by nothing. It is correctly colocated and
clean, which is what makes the secrets-slug spec beside it meaningful.

## Tracking

- ORCH-115 — API deployment
