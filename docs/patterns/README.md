---
type: nav
status: current
covers:
  - repo
freshness: tracks-code
bluf: Index of the reusable cross-cutting patterns; each entry is a self-contained why/how/gotchas reference that applies to more than one component.
---

# Patterns

> Parent: [docs/INDEX.md](../INDEX.md)

Reusable architecture patterns used across this cluster. Each doc is a self-contained
"why + how + gotchas" reference so the pattern can be re-applied consistently.

<!-- docs:gen:nav -->

| Doc                                                                          | What it covers                                                                                                                                                                                                               |
| ---------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| [cross-namespace-secret-reflection.md](cross-namespace-secret-reflection.md) | Mirror a namespace-scoped secret into the namespace that needs it with Kyverno (auto-annotate) plus reflector (copy), and aggregate many sources into one consumer with a single-writer job rather than per-source mutation. |

<!-- /docs:gen:nav -->
