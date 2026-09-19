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

EXPECT: taxonomy-structure

This page is missing the footer heading this sample's config requires. That string comes from
config, so this doc also pins that `required_footer` is data and not a hardcoded
`## Related Issues`.

Do NOT write the literal footer heading anywhere on this page, not even inside backticks or as
an example. The rule is a substring search over the body, so a single mention silently repairs
the fixture and the spec then passes while testing nothing. The declaration above names the
RULE, never the missing string, which is why it cannot cure what it declares.

ORCH-112 is mentioned here so the ticket rule has nothing to say about it.
