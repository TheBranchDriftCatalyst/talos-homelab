# Investigations

Dated deep-dive audits and analyses. Each is a point-in-time snapshot with evidence; remediation
is tracked in beads.

| Document                                                               | Description                                                                                                            | Date       |
| ---------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------- | ---------- |
| [cluster-audit-2026-08-09.md](cluster-audit-2026-08-09.md)             | Full six-domain audit run after the Cilium 1.16.6 → 1.20.0 campaign + PKI rotation; severity-ranked findings with evidence (epic TALOS-xgrl) | 2026-08-09 |
| [policy-reflection-observability.md](policy-reflection-observability.md) | Recommendation-only investigation into observing the Kyverno + reflector machinery that wires CNPG clusters into dbgate (TALOS-4b45) | — |

## Related

- [patterns/cross-namespace-secret-reflection.md](../patterns/cross-namespace-secret-reflection.md) — the pattern the second investigation observes
- [06-troubleshooting](../06-troubleshooting/README.md) — incident post-mortems
- [07-reference/cluster-crds.md](../07-reference/cluster-crds.md) — CRD catalog snapshot from the same audit window

---

## Related Issues

<!-- Beads tracking for this section -->
