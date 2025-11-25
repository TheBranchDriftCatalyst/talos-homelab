# Arr-Stack Storage Overlays

This directory contains composable storage backend configurations for the arr-stack application.

## Available Overlays

### fatboy-nfs (Production)

**Path**: `overlays/storage/fatboy-nfs/`

**Use Case**: Production deployments with NFS storage from Synology NAS (fatboy)

**Characteristics**:
- Storage Class: `fatboy-nfs-appdata`
- Access Mode: `ReadWriteMany` (supports multi-node access)
- Size: 1Ti media, 500Gi downloads
- Performance: Network-attached storage, shared across potential future nodes

**Used By**: `overlays/prod/kustomization.yaml`

### local-path (Development)

**Path**: `overlays/storage/local-path/`

**Use Case**: Local development with Tilt for fast iteration

**Characteristics**:
- Storage Class: `local-path` (Rancher local-path-provisioner)
- Access Mode: `ReadWriteOnce` (single-node only)
- Size: 100Gi media, 50Gi downloads (smaller for dev)
- Performance: Local disk, fastest for development workloads

**Used By**: Future Tilt development workflow (not currently applied to cluster)

## Usage

### With Kustomize

Production deployment:
```bash
kubectl apply -k applications/arr-stack/overlays/prod/
```

Development deployment (manual):
```bash
# Create a dev overlay that uses local-path storage
kubectl apply -k applications/arr-stack/overlays/storage/local-path/
```

### With Tilt (Future)

Tilt will reference the local-path overlay for fast local development:
```python
# Tiltfile example
k8s_yaml(kustomize('applications/arr-stack/overlays/storage/local-path/'))
```

## Notes

- **PostgreSQL uses local-path in all environments** - Databases should not use NFS for performance reasons
- The local-path overlay exists in git but is not currently applied to the cluster
- Production uses fatboy-nfs overlay via the prod kustomization
- Both overlays are compatible with the same base arr-stack configuration
