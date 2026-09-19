---
type: journal
status: current
freshness: frozen
summary: A doc that never says what it is about.
---

# Change Log

EXPECTED FINDING: `frontmatter-schema` (error), "missing required `covers`".

With no `covers:` there is nothing to colocate against, so the colocation rule skips this doc
entirely rather than guessing — one finding, not two.

## Tracking

- no ticket
