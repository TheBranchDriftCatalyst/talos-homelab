---
type: nav
status: current
covers:
  - monitoring
freshness: tracks-code
bluf: Index of the dashboard-level monitoring references; observability.md is the entry point for the stack itself.
pinned: covers resolves to infrastructure/base/monitoring, but this is the section index for docs/08-monitoring and belongs beside the document it indexes.
---

# Monitoring Reference

Dashboard-level reference for the observability stack. The stack itself — Alloy / Mimir / Loki /
Tempo / ClickStack, all in the `monitoring` namespace — is documented in
[observability.md](observability.md) alongside this file.

## Quick Navigation

<!-- docs:gen:nav -->

| Doc                                  | What it covers                                                                                                                                                                           |
| ------------------------------------ | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| [observability.md](observability.md) | An OTEL-native LGTM stack in one namespace — Alloy collects everything and fans out to Mimir, Loki, Tempo and ClickStack — and this explains why each backend is deployed the way it is. |

<!-- /docs:gen:nav -->

## Key Concepts

- Dashboards are **JSON + `GrafanaDashboard` CR only** — no generator scripts, no push helper.
- Regenerate the audit with `scripts/audit-grafana-dashboards.py`.
- Dashboard sources live in `infrastructure/base/monitoring/grafana-dashboards/`
  ([README](../../infrastructure/base/monitoring/grafana-dashboards/README.md)).

---

## Related Issues

<!-- Beads tracking for this section -->
