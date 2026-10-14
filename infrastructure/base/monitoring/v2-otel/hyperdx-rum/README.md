# hyperdx-rum

Browser RUM + session replay into ClickStack/HyperDX. The image and loader live
in the sister repo `workspace/catalyst-rum` (Forgejo `panda/catalyst-rum`); this
directory is only the cluster wiring.

## Status: STAGED, NOT WIRED IN

This directory is **deliberately absent from `../kustomization.yaml`**, so
nothing here is deployed yet. The image does not exist in Zot until the Forgejo
repo is created and CI runs once, and a `Deployment` sitting in
`ImagePullBackOff` would trip the baseline alerts for as long as that took.

### Enable sequence

1. Create the Forgejo repo and push the sister repo:

   ```bash
   cd ../catalyst-rum   # workspace/catalyst-rum
   git remote add origin https://forge.knowledgedump.space/panda/catalyst-rum.git
   git push -u origin main
   ```

   CI builds, smoke-tests and pushes
   `registry.knowledgedump.space/talos00-registry/catalyst-rum:sha-<7c>`.

2. Confirm the image is in Zot, then **re-pin** `server.yaml` from `:latest` to
   that `sha-<7c>` tag and its digest. `latest` on a stale tag is an upgrade
   trigger — it fast-forwards across every release at once the first time a node
   re-pulls, and a digest is strictly stronger.

3. Add one line to `../kustomization.yaml`:

   ```yaml
     - hyperdx-rum/
   ```

4. Reconcile and confirm the pod is Ready and serving:

   ```bash
   flux reconcile kustomization monitoring --with-source
   kubectl -n monitoring rollout status deploy/catalyst-rum
   curl -sI https://grafana.talos00/hyperdx-rum/rum.js | head -1   # expect 200
   ```

5. Only then opt Grafana in, by adding to
   `../grafana-instances/ingressroute.yaml`:

   ```yaml
         - name: hyperdx-rum-grafana
           namespace: monitoring
   ```

6. Load Grafana, click around, then check the table that was the whole point:

   ```bash
   kubectl -n monitoring exec chi-hyperdx-logs-logs-0-0-0 -- \
     clickhouse-client -q "SELECT count() FROM default.hyperdx_sessions"
   ```

## Why Grafana is the canary

LAN-only and SSO-gated, so the audience is just the operator. A heavy SPA, so
the data is actually interesting. Its IngressRoute is Flux-owned **in this
repo**, so no sister-repo change. It carries no other body rewriter (verified —
only `lan-only`). And if RUM breaks Grafana, HyperDX itself still works to show
why; instrumenting HyperDX first would have removed the tool needed to debug it.

## Two rules before adding any app

1. **Never** put an app behind both this and an `analytics-inject-*` or
   `catalyst-inject-*` middleware. Those are also `rewriteBody`, and chaining
   body rewriters is a documented silent failure mode here. Check the target
   route first.

2. Session replay records what the user sees. Masking is on by default and
   should stay; `media-private` surfaces are the wrong place for this.

## Signals, and which one this fixes

Measured 2026-10-14: `otel_logs` 4.52M, `otel_metrics_*` ~3.2M, `otel_traces`
564 — all flowing. `hyperdx_sessions` was **0**, and that is what this closes.
Note the sessions table carries the OTel **logs** schema, which is why the
loader must reach `/v1/logs` and not only `/v1/traces`.
