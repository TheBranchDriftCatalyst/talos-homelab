---
type: table
status: current
covers:
  - path:handbook/reference
freshness: follows-cluster
tickets:
  - ORCH-107
summary: Link handling, pinned in both directions.
---

# Link Reference

EXPECTED FINDINGS: exactly TWO `broken-links` (error). Everything else on this page must be
ignored, and that is the more valuable half of this fixture.

Reported — these targets do not exist:

- [gone](./no-such-file.md)
- [also gone](../design/deleted-doc.md)

NOT reported — this target does exist:

- [the handbook](../README.md)

NOT reported — off-repo and in-page targets are out of scope:

- [an external site](https://example.com/orchard)
- [an anchor on this page](#link-reference)
- [mail](mailto:orchard@example.com)

NOT reported — links inside a fenced block are an EXAMPLE, not content. If this one is ever
reported, `StripCode` stopped working and every code sample in the repo became a liability:

```markdown
See [the old layout](./this-path-never-existed.md) for how it used to work.
```

NOT reported — the same goes for an inline span: `[nope](./also-never-existed.md)`.

## Tracking

- ORCH-107 — link reference
