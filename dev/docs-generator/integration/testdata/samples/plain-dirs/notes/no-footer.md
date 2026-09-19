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

EXPECTED FINDINGS: `taxonomy-structure` (warn) for the missing footer heading this sample's
config requires, and nothing else. Tracked under PD-07.

DO NOT WRITE THAT HEADING ANYWHERE IN THIS BODY, not even inside backticks to explain what is
missing. The rule is `strings.Contains(d.Body, cfg.RequiredFooter)`, so naming it here satisfies
the check and the rule falls silent — which is what this file did until 2026-09-19, taking
`taxonomy-structure`'s ONLY coverage in this sample with it, and the golden was regenerated
against the silence so nothing complained.

Third occurrence of this class: see `missing-footer.md` and `ticket-drift.md` in the sibling
sample. A fixture that describes its own defect tends to cure it. Describe the defect by its
role, never by its literal text.

The footer requirement is data, not a constant: this sample requires one heading, flux-cluster
requires another, and talos-homelab a third. That is the point being pinned.
