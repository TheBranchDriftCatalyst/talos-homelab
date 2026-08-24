# Database Operators

Centralized database operator layer for provisioning databases via Kubernetes CRDs.

## Operators Deployed

| Operator | CRDs | Purpose |
|----------|------|---------|
| CloudNativePG | `Cluster`, `Backup`, `ScheduledBackup`, `Pooler` | PostgreSQL clusters |
| MongoDB Community | `MongoDBCommunity` | MongoDB replica sets |
| MinIO Operator | `Tenant`, `PolicyBinding` | S3-compatible object storage |

## Usage

### PostgreSQL (CloudNativePG)

```yaml
apiVersion: postgresql.cnpg.io/v1
kind: Cluster
metadata:
  name: my-postgres
  namespace: my-app
spec:
  instances: 3
  storage:
    size: 10Gi
    storageClass: local-path
  bootstrap:
    initdb:
      database: mydb
      owner: myuser
```

**Service endpoints created:**
- `my-postgres-rw` - Read/write (primary)
- `my-postgres-ro` - Read-only (replicas)
- `my-postgres-r` - Any instance

### MongoDB (Community Operator)

```yaml
apiVersion: mongodbcommunity.mongodb.com/v1
kind: MongoDBCommunity
metadata:
  name: my-mongodb
  namespace: my-app
spec:
  members: 3
  type: ReplicaSet
  version: "7.0.14"
  security:
    authentication:
      modes: ["SCRAM"]
  users:
    - name: myuser
      db: mydb
      passwordSecretRef:
        name: my-mongodb-password
      roles:
        - name: readWrite
          db: mydb
```

**Service endpoint created:**
- `my-mongodb-svc` - Replica set connection

### MinIO (Operator)

```yaml
apiVersion: minio.min.io/v2
kind: Tenant
metadata:
  name: my-minio
  namespace: my-app
spec:
  configuration:
    name: my-minio-env-config
  pools:
    - name: pool-0
      servers: 1
      volumesPerServer: 1
      volumeClaimTemplate:
        spec:
          storageClassName: local-path
          resources:
            requests:
              storage: 50Gi
```

**Service endpoints created:**
- `minio` - S3 API
- `my-minio-console` - Web console

## Example Deployment

See `applications/scratch/` for working examples of all three database types plus DbGate UI.

### Scratch Namespace Services

| Service | URL | Credentials |
|---------|-----|-------------|
| DbGate UI | http://dbgate.talos00 | No login required |
| PostgreSQL | scratch-postgres-rw.scratch:5432 | scratch_app / scratch-app-password |
| MongoDB | scratch-mongodb-svc.scratch:27017 | scratch_user / scratch-mongo-password |

### /etc/hosts Entry

```
192.168.1.54  dbgate.talos00
```

## Flux Dependencies

```
namespaces → storage → databases → scratch
```

Deploy order:
1. `databases` Kustomization deploys operators
2. `scratch` Kustomization deploys example CRs (depends on databases)
