---
title: Ingress Design
type: design
status: current
covers:
  - path:handbook/design
freshness: follows-code
tickets:
  - ORCH-106
summary: A doc carrying a key that must never appear.
---

# Ingress Design

## Context

EXPECT: frontmatter-schema

The defect is the banned key in the frontmatter above. Verified against markdownlint 0.41.1: it
both suppresses MD041 and turns the H1 above into an MD025 duplicate-heading error.

That key is not in `key_order`, so it is invisible to the ordering check and this doc raises
exactly one finding.

## Tracking

- ORCH-106 — ingress design
