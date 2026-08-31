# Patterns

> Parent: [docs/INDEX.md](../INDEX.md)

Reusable architecture patterns used across this cluster. Each doc is a self-contained
"why + how + gotchas" reference so the pattern can be re-applied consistently.

| Pattern | What it solves |
|---------|----------------|
| [cross-namespace-secret-reflection.md](cross-namespace-secret-reflection.md) | Make a secret produced in namespace A usable in namespace B — automatically, for current + future producers — via Kyverno (auto-annotate) + emberstack/reflector (mirror). Worked example: auto-connecting dbgate to every CNPG Postgres cluster. |
| [handoff-crd-driven-auto-registration.md](handoff-crd-driven-auto-registration.md) | **Portable handoff** — hand this to an agent re-implementing the dbgate/CNPG auto-registration in another repo or cluster. Self-contained: all four parts (Kyverno auto-annotate + reflector mirror + single-writer CRD-discovery sync + `envFrom` consumer), the failed designs that must not be re-tried, adaptation seams, and acceptance criteria. |
