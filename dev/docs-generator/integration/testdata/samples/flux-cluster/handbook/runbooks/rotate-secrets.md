---
type: runbook
status: current
covers:
  - secrets-operator
  - secrets-store
freshness: follows-code
tickets:
  - ORCH-104
summary: Rotate the signing key without dropping traffic.
pinned: the two secrets components have no shared doc home; keep the procedure with its siblings.
---

# Rotate Secrets

## Stop condition

Stop when `orchard-api` serves a token signed by the new key.

1. Scale the operator to zero.
2. Replace the key material in the store.
3. Scale the operator back up.
4. Confirm a fresh token verifies.

This doc covers BOTH components declared in the single manifest
[fleet/prod-west/secrets.yaml](../../fleet/prod-west/secrets.yaml). Their longest common
ancestor is `platform`, which is a grouping root, so the colocation rule would exile this doc
to a cross-cutting home; `pinned:` records why it stays. Zero findings expected.

## Tracking

- ORCH-104 — secret rotation
