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

Deployed after the gateway; `orchard-web` in turn depends on this. That three-level chain is
declared in the Kustomizations and is, today, read by nothing.

## Tracking

- ORCH-115 — API deployment
