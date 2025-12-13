# OTEL Stack Migration - Design Document

**Beads:** `TALOS-nh8`
**Status:** Implementation
**Last Updated:** 2025-12-13

---

## TL;DR

Migrate from current observability stack (OpenSearch/Graylog/Fluent-Bit) to OTEL-native LGTM stack (Loki/Grafana/Tempo/Mimir) with Grafana Alloy as the unified collector.

**Key Decision:** Run both stacks in parallel (v1/v2) for evaluation before cutover.

**V2 Stack Components:**
- **Operators:** OTEL Operator, Tempo Operator, Grafana Operator (existing)
- **Data Plane:** Alloy, Mimir, Loki, Tempo
- **CRDs:** OpenTelemetryCollector, Instrumentation, TempoMonolithic, GrafanaDatasource

---

## Directory Structure

```
infrastructure/base/
├── monitoring/
│   ├── shared/                    # Shared across v1 and v2
│   │   ├── namespace.yaml
│   │   ├── grafana-operator/      # Grafana Operator (manages Grafana CRs)
│   │   └── prometheus-operator/   # If we split from kube-prometheus-stack
│   │
│   ├── v1/                        # Current stack (to be deprecated)
│   │   ├── kube-prometheus-stack/ # Prometheus + Grafana + Alertmanager
│   │   ├── grafana-dashboards/
│   │   ├── grafana-datasources/
│   │   └── servicemonitors/
│   │
│   └── v2-otel/                   # New OTEL-native stack
│       ├── mimir/                 # Metrics backend (replaces Prometheus long-term)
│       ├── loki/                  # Logs (already deployed, move here)
│       ├── tempo/                 # Traces (NEW)
│       ├── alloy/                 # Unified collector (replaces OTEL Collector)
│       ├── grafana-dashboards/
│       └── grafana-datasources/
│
├── observability/                 # DEPRECATED after migration
│   ├── v1/                        # Current (OpenSearch/Graylog)
│   │   ├── opensearch/
│   │   ├── graylog/
│   │   ├── fluent-bit/
│   │   └── mongodb/
│   │
│   └── loki/                      # Move to monitoring/v2-otel/
```

---

## Component Analysis

### Grafana Alloy (Replaces OTEL Collector + Grafana Agent)

| Aspect | Details |
|--------|---------|
| **What** | Grafana's OpenTelemetry-native collector |
| **Replaces** | OTEL Collector, Grafana Agent (EOL Nov 2025), Fluent Bit |
| **Why** | Single collector for metrics, logs, traces |
| **CRDs** | ❌ No operator/CRDs - configured via ConfigMap |
| **Helm** | `grafana/alloy` chart |

```yaml
# Alloy config example
otelcol.receiver.otlp "default" {
  grpc { endpoint = "0.0.0.0:4317" }
  http { endpoint = "0.0.0.0:4318" }
}

otelcol.exporter.loki "default" {
  forward_to = [loki.write.default.receiver]
}
```

### Mimir (Replaces/Augments Prometheus)

| Aspect | Details |
|--------|---------|
| **What** | Horizontally scalable Prometheus-compatible metrics backend |
| **Replaces** | Prometheus (for long-term storage) OR runs alongside |
| **Why** | Better scalability, native OTLP, multi-tenancy |
| **CRDs** | ❌ No operator - Helm only |
| **Helm** | `grafana/mimir-distributed` |

**Decision Point:** For homelab, Prometheus is fine. Mimir adds complexity.
- **Option A:** Keep Prometheus, add OTLP remote-write receiver
- **Option B:** Replace with Mimir for full LGTM experience

### Tempo (NEW - Traces)

| Aspect | Details |
|--------|---------|
| **What** | Distributed tracing backend |
| **CRDs** | ✅ Tempo Operator available (`TempoStack`, `TempoMonolithic`) |
| **Helm** | `grafana/tempo` (simple) or use Tempo Operator |

### Loki (Already Deployed)

| Aspect | Details |
|--------|---------|
| **Current** | v6.46.0, single binary mode, observability namespace |
| **Move to** | `monitoring/v2-otel/loki/` |
| **CRDs** | ❌ No operator exists |

---

## CRD Summary

| Component | Helm Provides CRDs? | Operator Available? | Recommendation |
|-----------|--------------------|--------------------|----------------|
| **Prometheus** | ✅ Yes (via kube-prometheus-stack) | ✅ Already installed | Keep |
| **Grafana** | ❌ No | ✅ Already installed | Keep |
| **Alloy** | ❌ No | ❌ No | Use Helm |
| **Loki** | ❌ No | ❌ No | Use Helm |
| **Tempo** | ❌ No | ✅ Yes (optional) | Helm or Operator |
| **Mimir** | ❌ No | ❌ No | Use Helm (if needed) |
| **OTEL Collector** | ❌ No | ✅ Yes | Skip (use Alloy) |

**Key Insight:** Most LGTM components don't have CRDs - they're configured via Helm values. The CRD-based management comes from:
- Prometheus Operator (ServiceMonitor, PodMonitor, PrometheusRule)
- Grafana Operator (GrafanaDashboard, GrafanaDatasource)
- Tempo Operator (optional)

---

## Migration Phases

### Phase 1: Restructure Directories
- [ ] Create `monitoring/shared/`, `monitoring/v1/`, `monitoring/v2-otel/`
- [ ] Move current kube-prometheus-stack to `v1/`
- [ ] Move Loki from observability to `v2-otel/`

### Phase 2: Deploy V2 Stack
- [ ] Deploy Alloy (collector)
- [ ] Deploy Tempo (traces)
- [ ] Configure Grafana datasources for v2
- [ ] Test Claude Code OTLP export

### Phase 3: Parallel Running
- [ ] Both stacks running
- [ ] Compare resource usage
- [ ] Validate log/metric parity

### Phase 4: Cutover
- [ ] Switch Fluent Bit → Alloy for cluster logs
- [ ] Deprecate OpenSearch/Graylog
- [ ] Update Flux kustomizations

---

## Open Questions

1. **Mimir vs Prometheus?**
   - Prometheus: Simpler, already working, good for homelab
   - Mimir: Future-proof, native OTLP, but more resources
   - **Recommendation:** Start with Prometheus + OTLP receiver, migrate to Mimir later if needed

2. **Tempo Operator vs Helm?**
   - Operator: CRD-based, GitOps friendly
   - Helm: Simpler, less moving parts
   - **Recommendation:** Helm for homelab simplicity

3. **Alloy vs OTEL Collector?**
   - Alloy: Grafana-native, single config language, better Loki/Tempo integration
   - OTEL Collector: Vendor-neutral, more community support
   - **Recommendation:** Alloy (tighter LGTM integration)

---

## Related Issues

- `TALOS-nh8` - OTEL Stack Evaluation epic
- `TALOS-3of` - Deploy OTEL Collector (update to Alloy)
- `TALOS-jzy` - Deploy Loki (already done, needs relocation)
- `TALOS-mhk` - Deploy Tempo
- `TALOS-t7u` - Configure Claude Code OTLP
