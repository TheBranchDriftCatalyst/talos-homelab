# Monitoring Reference

Dashboard-level reference for the observability stack. The stack itself is documented in the root
[OBSERVABILITY.md](../../OBSERVABILITY.md) (Alloy / Mimir / Loki / Tempo / ClickStack, all in the
`monitoring` namespace).

## Quick Navigation

| Document                                                                 | Description                                                                                                | When to Read                                     |
| ------------------------------------------------------------------------ | ---------------------------------------------------------------------------------------------------------- | ------------------------------------------------ |
| [GRAFANA-DASHBOARDS.md](GRAFANA-DASHBOARDS.md)                           | Index of every Grafana dashboard in the cluster, by folder and purpose                                     | Finding or adding a dashboard                    |
| [GRAFANA-DASHBOARD-QUERY-AUDIT.md](GRAFANA-DASHBOARD-QUERY-AUDIT.md)     | Generated per-panel query verification for every live `GrafanaDashboard` CR; `EMPTY` = review item          | Auditing dashboards after a metrics-stack change |

## Key Concepts

- Dashboards are **JSON + `GrafanaDashboard` CR only** — no generator scripts, no push helper.
- Regenerate the audit with `scripts/audit-grafana-dashboards.py`.
- Dashboard sources live in `infrastructure/base/monitoring/grafana-dashboards/`
  ([README](../../infrastructure/base/monitoring/grafana-dashboards/README.md)).

---

## Related Issues

<!-- Beads tracking for this section -->
