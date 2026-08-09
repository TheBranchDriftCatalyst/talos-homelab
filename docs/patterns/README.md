# Patterns

Reusable architecture patterns used across this cluster. Each doc is a self-contained
"why + how + gotchas" reference so the pattern can be re-applied consistently.

| Pattern | What it solves |
|---------|----------------|
| [cross-namespace-secret-reflection.md](cross-namespace-secret-reflection.md) | Make a secret produced in namespace A usable in namespace B — automatically, for current + future producers — via Kyverno (auto-annotate) + emberstack/reflector (mirror). Worked example: auto-connecting dbgate to every CNPG Postgres cluster. |
