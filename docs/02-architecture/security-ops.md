---
type: architecture
status: superseded
covers:
  - crowdsec
  - falco
  - honeypots
  - iocaine
freshness: frozen
bluf: Pointer. The security architecture now lives beside the manifests it describes.
superseded_by: infrastructure/base/security/README.md
pinned: kept in docs/ as a redirect while three index pages outside this migration's scope still link here
---

# Security ops

This page has moved. The security architecture is now colocated with the manifests it
describes, so that a change to a component and a change to its documentation are the same
commit.

## TL;DR

- **Start here:** [infrastructure/base/security/README.md](../../infrastructure/base/security/README.md)
  — how detection, decision and enforcement divide, and why there are two enforcement planes.
- [crowdsec/](../../infrastructure/base/security/crowdsec/README.md) — the decision engine,
  and the invariants around remediation codes, allowlists and scenario promotion.
- [honeypots/](../../infrastructure/base/security/honeypots/README.md) — the traps, the front
  that fronts them, and the cage around them.
- [iocaine/](../../infrastructure/base/security/iocaine/README.md) — the crawler tarpit.
- [falco/](../../infrastructure/base/security/falco/README.md) — runtime detection and the
  honeypot breach tripwire.

Verification procedures live with their components:
[CrowdSec](../../infrastructure/base/security/crowdsec/crowdsec-verification.md) and
[honeypot exposure](../../infrastructure/base/security/honeypots/cowrie-public-exposure.md).

## Related Issues

- TALOS-hg7 — security-ops epic
