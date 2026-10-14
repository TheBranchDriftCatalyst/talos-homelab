# hyperdx-rum

Browser RUM + session replay into ClickStack/HyperDX. The image and loader live
in the sister repo `workspace/catalyst-rum` (Forgejo `panda/catalyst-rum`); this
directory is only the cluster wiring.

## Status: LIVE

Wired into `../kustomization.yaml`. Image built by Forgejo from
`panda/catalyst-rum` and pinned by tag **and** digest.

### Opted-in apps

| App | Where the injection is declared | Replay |
| --- | --- | --- |
| `grafana.talos00` | `middlewares.yaml` here | masked inputs + masked text |
| `boomtime.knowledgedump.space` | `../../analytics/sites-middlewares.yaml` | masked inputs, **text visible** |
| `amberdark.net` | `../../analytics/sites-middlewares.yaml` | masked inputs, **text visible** |

boomtime and amberdark are declared in the analytics file, not here, because
both already carry a Plausible `rewriteBody` and **chaining two body rewriters
is a silent failure mode** — their RUM tag is emitted from the same single
rewrite. Only apps with no existing injector get a middleware in this directory.

### Two ingest routes, on purpose

`hyperdx-rum` is hostless and `lan-only`. `hyperdx-rum-public` is scoped to the
named public hosts with **no** `lan-only`, at priority 10100 so it beats the
hostless rule on a host both match. `lan-only` is RFC1918-only, so without the
second route every public visitor's beacon would be 403'd — empty sessions
table, no server-side error, console-only symptom.

Public exposure is therefore an explicit list someone has to edit, not a blanket
opening that arrives as a side effect of instrumenting an app.

### Verifying

```bash
kubectl -n monitoring rollout status deploy/catalyst-rum
curl -sI https://grafana.talos00/hyperdx-rum/rum.js | head -1       # 200
curl -s https://boomtime.knowledgedump.space/ | grep -o 'hyperdx-rum/rum.js'
kubectl -n monitoring exec chi-hyperdx-logs-logs-0-0-0 -- \
  clickhouse-client -q "SELECT ServiceName, count() FROM default.hyperdx_sessions GROUP BY ServiceName"
```

### Updating the SDK or loader

Push to `panda/catalyst-rum`; CI publishes `sha-<7c>`. Then re-pin `server.yaml`
to that tag and digest. Do not move the pin to `latest`.

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
