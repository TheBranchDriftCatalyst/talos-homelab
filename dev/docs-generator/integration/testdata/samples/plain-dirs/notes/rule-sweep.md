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

Three rules, all on this one page:

EXPECT: frontmatter-schema
EXPECT: covers-resolves
EXPECT: broken-links

…raised by the banned key in the frontmatter, the second `covers:` token, and
[this link](./vanished.md) respectively. One page tripping three rules is the case that proves
reconciliation is keyed on (path, rule) rather than on the path alone.

`pinned:` suppresses the colocation finding that `notifications` would otherwise raise.

## Follow-up

- PD-06 — rule sweep
