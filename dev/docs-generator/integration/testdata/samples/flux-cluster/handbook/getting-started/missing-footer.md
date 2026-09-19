---
type: guide
status: current
covers:
  - path:handbook/getting-started
freshness: follows-code
tickets:
  - ORCH-112
summary: A guide that forgot its footer.
---

# Upgrading Orchard

## Start here

EXPECTED FINDING: `taxonomy-structure` (warn), missing the required footer. That footer string
comes from config, so this doc also pins that `required_footer` is data and not a hardcoded
`## Related Issues`.

Do NOT write the literal footer heading anywhere on this page, not even inside backticks or as
an example. The rule is a substring search over the whole file, frontmatter included, so a
single mention silently repairs the fixture and the spec then passes while testing nothing.

ORCH-112 is mentioned here so the ticket rule has nothing to say about it.
