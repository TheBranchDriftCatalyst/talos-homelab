# crossplane-demo `flex`

A tiny Go "flex" service for the crossplane-demo. It trivially exercises every
provisioned backend and reports **OK / FAIL / SKIPPED** per subsystem. It is
driven by the Jest integration test — either over HTTP (`GET /run`) or via
`kubectl exec <pod> -- /flex -once`.

Each subsystem check reads its endpoint + credentials from environment
variables. **If a required env var is missing the subsystem is `skipped`, not
failed.** Every check has its own ~10s timeout (argo 60s, celery 30s) and can
never panic the process — errors are captured into the result.

## Endpoints

| Method / Path | Behaviour |
| ------------- | --------- |
| `GET /healthz` | Liveness → `200 ok`. |
| `GET /run`     | Runs ALL checks, returns JSON (HTTP **200 always**; per-item `ok`). |
| `GET /status`  | Same results rendered as an HTML table for humans. |

JSON shape:

```json
{
  "results": [
    { "subsystem": "minio", "ok": true, "detail": "bucket \"demo\" put/get roundtrip ok (13 bytes)" },
    { "subsystem": "argo", "ok": false, "skipped": true, "detail": "no kube config ..." }
  ],
  "all_ok": true
}
```

`all_ok` is true when **no check FAILED**; skipped checks do not count against it.

## CLI

```bash
/flex            # start HTTP server on :8080 (override with -addr or $FLEX_ADDR)
/flex -once      # run checks once, print the JSON report to stdout, exit
                 #   exit code 0 when all_ok, 1 otherwise (handy for the Jest test)
```

## Subsystems & environment variables

| Subsystem   | Required env (skipped if unset)                  | Optional / defaults |
| ----------- | ------------------------------------------------- | ------------------- |
| minio       | `MINIO_ENDPOINT`, `MINIO_ACCESS_KEY`, `MINIO_SECRET_KEY` | `MINIO_BUCKET`=`demo`, `MINIO_SECURE`=`false` |
| rabbitmq    | `RABBITMQ_URL`                                    | `RABBITMQ_QUEUE`=`demo` |
| dragonfly   | `REDIS_ADDR`                                      | `REDIS_PASSWORD`="" |
| clickhouse  | `CLICKHOUSE_ADDR`                                 | `CLICKHOUSE_USER`=`default`, `CLICKHOUSE_PASSWORD`="", `CLICKHOUSE_DATABASE`=`default` |
| opensearch  | `OPENSEARCH_URL`                                  | `OPENSEARCH_USER`, `OPENSEARCH_PASSWORD` (TLS verify disabled — operator self-signed) |
| argo        | in-cluster config (falls back to kubeconfig)      | `DEMO_NAMESPACE`=`crossplane-demo`, `ARGO_WORKFLOWTEMPLATE`=`demo-hello`, `ARGO_SA` |
| crossplane  | in-cluster config (falls back to kubeconfig)      | `DEMO_NAMESPACE`=`crossplane-demo`, `CROSSPLANE_CONFIGMAP`=`crossplane-made-this` |
| celery      | `RABBITMQ_URL` **and** `REDIS_ADDR`               | `CELERY_QUEUE`=`celery`, `CELERY_TASK`=`demo.flex`, `CELERY_MARKER_KEY`=`celery:flex:done` |

Server-only: `FLEX_ADDR` (default `:8080`).

What each check does:

1. **minio** — MakeBucket (if absent) → PutObject → GetObject → compare bytes.
2. **rabbitmq** — declare queue → publish → `basic.get` consume → verify body.
3. **dragonfly** — SET a random value → GET → compare.
4. **clickhouse** — `CREATE TABLE IF NOT EXISTS demo_flex ...` → INSERT → `SELECT count()` ≥ 1.
5. **opensearch** — index a doc into `demo-flex` (refresh) → search → assert hits ≥ 1.
6. **argo** — create a `Workflow` from `workflowTemplateRef` → poll `.status.phase` for `Succeeded` (≤60s). Uses the dynamic client (no argo API vendoring).
7. **crossplane** — read ConfigMap `crossplane-made-this` in `DEMO_NAMESPACE`; OK if it exists (proves the managed `Object` reconciled).
8. **celery** — publish a Celery protocol-v2 task onto the celery queue (via RabbitMQ), then poll Dragonfly for the worker's marker key (≤30s).

> The `argo` / `crossplane` checks need a Kubernetes API. In-cluster this is the
> Pod's service account (make sure its RBAC allows creating `workflows` and
> getting `configmaps` in `DEMO_NAMESPACE`). Off-cluster (local `-once`) it
> falls back to your kubeconfig; if neither is available the checks are skipped.

## Build & push

The service ships as a static binary on `distroless/static:nonroot`.

```bash
cd applications/crossplane-demo/flex

# Build (multi-stage: golang:1.23 -> distroless/static, nonroot, static binary)
docker build -t registry.talos00/crossplane-demo-flex:latest .

# Push to the in-cluster Nexus registry. NodePort isn't externally reachable on
# Talos, so push via a port-forward (see repo CLAUDE.md "Nexus Repository Usage").
kubectl port-forward -n registry svc/nexus-docker 5000:5000 &
docker tag  registry.talos00/crossplane-demo-flex:latest localhost:5000/crossplane-demo-flex:latest
docker push localhost:5000/crossplane-demo-flex:latest
```

Reference the image in the demo Deployment as
`registry.talos00/crossplane-demo-flex:latest`.
