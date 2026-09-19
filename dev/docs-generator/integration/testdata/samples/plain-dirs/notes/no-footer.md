---
type: log
status: current
covers:
  - path:notes
freshness: frozen
tickets:
  - PD-07
---

# Release Log

EXPECTED FINDING: `taxonomy-structure` (warn), missing the `## Follow-up` footer. That string
comes from this sample's config, which is how it pins that `required_footer` is data — the
flux-cluster sample demands `## Tracking` and talos-homelab demands `## Related Issues`.
