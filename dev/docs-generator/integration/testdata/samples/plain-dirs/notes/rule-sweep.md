---
title: Rule Sweep
type: note
status: current
covers:
  - notifications
  - no-such-service
freshness: live
tickets:
  - PD-06
pinned: deliberately covers a bogus token; keep it beside the other note fixtures.
---

# Rule Sweep

EXPECTED FINDINGS, all on this one page:

- `frontmatter-schema` (error) — banned key `title`
- `covers-resolves` (error) — `no-such-service` matches no component
- `broken-links` (error) — [gone](./vanished.md)

`pinned:` suppresses the colocation finding that `notifications` would otherwise raise.

## Follow-up

- PD-06 — rule sweep
