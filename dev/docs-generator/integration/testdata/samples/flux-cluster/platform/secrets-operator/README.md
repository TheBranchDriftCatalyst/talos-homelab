---
type: design
status: current
covers:
  - secrets-operator
freshness: follows-code
tickets:
  - ORCH-116
summary: The operator half of the secrets stack.
---

# Secrets Operator

## Context

`secrets-operator` and `secrets-store` are declared in ONE manifest,
[fleet/prod-west/secrets.yaml](../../fleet/prod-west/secrets.yaml), and they are two different
components with two different paths.

EXPECT: none

This doc is the teeth on that: it covers `secrets-operator` and lives at
`platform/secrets-operator/`. If the two slugs ever collapse again, `covers: secrets-operator`
resolves to `platform/secrets-store` and `colocation` fires here. A passing run of this spec is
a statement that the slugs are still distinct.

## Tracking

- ORCH-116 — split the secrets slugs
