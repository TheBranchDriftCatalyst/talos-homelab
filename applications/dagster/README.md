# Dagster Platform

Shared orchestration platform for all data pipelines. Webserver + daemon + Postgres — any pipeline registers as a code location.

**UI**: http://dagster.talos00
**Namespace**: `dagster`

## Architecture

```
┌─────────────────────── dagster namespace ───────────────────────┐
│                                                                  │
│  dagster-webserver ──────► dagster-postgres (port 5432)         │
│    (port 3000)              PVC: local-path 5Gi                 │
│    PVC: dagster-home                                             │
│    (fatboy-nfs 10Gi)                                             │
│                                                                  │
│  dagster-daemon ────────► dagster-postgres                      │
│    PVC: dagster-home                                             │
│                                                                  │
│  ClusterRole RBAC ──────► can launch K8s Jobs in ANY namespace  │
└──────────────────────────────────────────────────────────────────┘
         ▲                           ▲
         │ IngressRoute              │ K8sRunLauncher
         │ dagster.talos00           │ creates Jobs per run
         │                           │
    ┌────┴────┐              ┌───────┴────────┐
    │ Browser │              │  Pipeline Runs  │
    └─────────┘              │  (K8s Jobs)     │
                             └────────────────┘
                                     ▲
                                     │ gRPC (port 4000)
                             ┌───────┴────────┐
                             │ Code Locations  │
                             │ (your pipeline) │
                             └────────────────┘
```

## How to Register a Code Location

Each pipeline runs as a separate Deployment that serves its Dagster definitions via gRPC. The shared platform discovers them via `workspace.yaml`.

### 1. Build your pipeline image

```dockerfile
FROM python:3.11-slim
RUN pip install dagster dagster-k8s dagster-postgres
COPY my_pipeline/ /app/my_pipeline/
WORKDIR /app
CMD ["dagster", "code-server", "start", "--host", "0.0.0.0", "--port", "4000", "--module-name", "my_pipeline"]
```

### 2. Deploy as K8s Deployment + Service

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: my-pipeline
  namespace: dagster  # or your own namespace
spec:
  replicas: 1
  selector:
    matchLabels:
      app: my-pipeline
  template:
    spec:
      containers:
        - name: code-server
          image: your-registry/my-pipeline:latest
          ports:
            - containerPort: 4000
---
apiVersion: v1
kind: Service
metadata:
  name: my-pipeline
  namespace: dagster
spec:
  ports:
    - port: 4000
  selector:
    app: my-pipeline
```

### 3. Add to workspace.yaml

Edit `applications/dagster/workspace.yaml` ConfigMap:

```yaml
data:
  workspace.yaml: |
    load_from:
      - grpc_server:
          host: my-pipeline.dagster.svc.cluster.local
          port: 4000
          location_name: my_pipeline
```

For code locations in other namespaces, use the FQDN:
```yaml
host: my-pipeline.other-namespace.svc.cluster.local
```

### 4. Re-apply

```bash
kubectl apply -k applications/dagster/
```

The webserver picks up the new code location automatically.

## Architecture Decision Records

### ADR-1: Postgres as separate Deployment

**Decision**: Postgres runs as its own Deployment, not a sidecar container.

**Why**: When Postgres is a sidecar, restarting the daemon or webserver also kills the database. With a separate Deployment, the database survives component restarts, reducing data corruption risk and improving availability.

### ADR-2: ClusterRole RBAC (not Role)

**Decision**: The `dagster` ServiceAccount has a ClusterRole, not a namespace-scoped Role.

**Why**: The K8sRunLauncher needs to create K8s Jobs wherever pipeline workloads belong — downloads namespace, corpus-dev, etc. A namespace-scoped Role would confine job launching to the dagster namespace only.

### ADR-3: K8sRunLauncher

**Decision**: Pipeline runs execute as K8s Jobs, not in the webserver or daemon process.

**Why**: Isolates pipeline execution from the platform. A misbehaving pipeline can't crash the webserver or daemon. Each run gets its own pod with dedicated resources, and K8s handles scheduling, retries, and cleanup.

### ADR-4: Storage split

**Decision**: `local-path` for Postgres, `fatboy-nfs-appdata` for dagster-home.

**Why**: Postgres needs fast I/O for queries — local SSD storage via `local-path` provides this. Dagster-home stores logs, schedules, and sensor state — NFS (`fatboy-nfs-appdata`) provides durability and survives node failures.

### ADR-5: Empty workspace pattern

**Decision**: `workspace.yaml` starts with `load_from: []`. Code locations are added as pipelines are built.

**Why**: The platform deploys independently of any pipeline. Pipelines register themselves by adding entries to the workspace ConfigMap. This decouples platform lifecycle from pipeline lifecycle.

## File Layout

```
applications/dagster/
├── kustomization.yaml       # Kustomize root
├── namespace.yaml           # dagster namespace
├── rbac.yaml                # ServiceAccount + ClusterRole + ClusterRoleBinding
├── pvc.yaml                 # dagster-home PVC (fatboy-nfs-appdata, 10Gi)
├── postgres.yaml            # Postgres Deployment + Service + PVC (local-path, 5Gi)
├── dagster-instance.yaml    # ConfigMap: dagster.yaml (storage + run launcher)
├── workspace.yaml           # ConfigMap: workspace.yaml (code locations)
├── deployment.yaml          # Webserver + Daemon Deployments
├── service.yaml             # ClusterIP for webserver (port 3000)
├── ingressroute.yaml        # Traefik: dagster.talos00
├── Tiltfile                 # Tilt ops dashboard
└── dashboard.sh             # Namespace status dashboard
```

## Operations

### Deploy / Update

```bash
kubectl apply -k applications/dagster/
```

### Check status

```bash
kubectl get pods -n dagster
kubectl get pvc -n dagster
```

### View logs

```bash
# Webserver
kubectl logs -n dagster deploy/dagster-webserver --tail=50

# Daemon
kubectl logs -n dagster deploy/dagster-daemon --tail=50

# Postgres
kubectl logs -n dagster deploy/dagster-postgres --tail=50
```

### Verify config

```bash
kubectl exec -n dagster deploy/dagster-webserver -- cat /opt/dagster/dagster_home/dagster.yaml
```

### Restart components

```bash
kubectl rollout restart deploy/dagster-webserver -n dagster
kubectl rollout restart deploy/dagster-daemon -n dagster
```

### Credentials

- **Postgres**: `dagster` / `dagster-homelab` (database: `dagster`)

## Troubleshooting

| Symptom | Check |
|---------|-------|
| Daemon crash-looping | `kubectl logs -n dagster deploy/dagster-daemon --previous` |
| Webserver not loading | Verify Postgres is ready: `kubectl get pods -n dagster -l app.kubernetes.io/component=postgres` |
| Code location not appearing | Check gRPC service is reachable: `kubectl exec -n dagster deploy/dagster-webserver -- nc -z <service> 4000` |
| Runs not launching | Check RBAC: `kubectl auth can-i create jobs --as=system:serviceaccount:dagster:dagster -n <target-namespace>` |

---

## Related Issues

- TALOS-z7ns — Prune old Dagster from corpus-dev and migrate reusable config
- TALOS-x48d — Whisper transcription pipeline as Dagster code location
- TALOS-1owj — Congress data pipeline ingester as Dagster code location
