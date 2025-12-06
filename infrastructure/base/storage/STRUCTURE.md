# Storage Architecture

This document describes the storage mount structure for the homelab cluster.

## Overview

The cluster uses two NAS devices for storage:

- **TrueNAS** (192.168.1.200) - Primary media storage with large capacity
- **Synology** (192.168.1.234) - Secondary storage and app configurations

All NFS variables are substituted via Flux postBuild from `cluster-settings.yaml`.

## Storage Classes

| Storage Class          | Type              | Use Case                                   |
| ---------------------- | ----------------- | ------------------------------------------ |
| `local-path` (default) | Local provisioner | Databases, pods needing fast local storage |
| `truenas-nfs`          | Static NFS        | Large media libraries                      |
| `synology-nfs`         | Static NFS        | Media libraries, downloads                 |
| `fatboy-nfs-appdata`   | Dynamic NFS       | App configs (\*arr apps)                   |

## NAS Mount Structure

### TrueNAS (192.168.1.200)

```
/mnt/megapool/
├── media/
│   ├── movies/      → truenas-media-movies PV
│   ├── tv/          → truenas-media-tv PV
│   ├── music/       → truenas-media-music PV
│   └── books/       → truenas-media-books PV
└── downloads/
    ├── complete/    → truenas-downloads-complete PV
    └── incomplete/  → truenas-downloads-incomplete PV
```

### Synology (192.168.1.234)

```
/volume1/
├── appdata/         → Dynamic provisioning (fatboy-nfs-appdata)
│   ├── sonarr/
│   ├── radarr/
│   ├── prowlarr/
│   ├── readarr/
│   ├── bazarr/
│   └── ...
├── media/
│   ├── movies/      → synology-media-movies PV
│   ├── tv/          → synology-media-tv PV
│   ├── music/       → synology-media-music PV
│   └── books/       → synology-media-books PV
└── downloads/
    ├── complete/    → synology-downloads-complete PV
    └── incomplete/  → synology-downloads-incomplete PV
```

## App Storage Pattern

### Media Apps (\*arr stack)

Each media app gets:

1. **Config volume** - Dynamic PVC using `fatboy-nfs-appdata` (Synology /volume1/appdata/)
2. **Media volume(s)** - Static PVC(s) bound to TrueNAS or Synology media PVs
3. **Downloads volume** - Static PVC bound to downloads PV

Example for Sonarr:

```yaml
volumes:
  - name: config
    persistentVolumeClaim:
      claimName: sonarr-config # Dynamic, fatboy-nfs-appdata
  - name: media-tv
    persistentVolumeClaim:
      claimName: truenas-tv # Static, TrueNAS
  - name: downloads
    persistentVolumeClaim:
      claimName: synology-downloads-complete # Static, Synology
```

### Databases

Databases should use `local-path` storage class for performance:

```yaml
spec:
  storageClassName: local-path
```

## PVC Naming Convention

| Pattern        | Example           | Description                |
| -------------- | ----------------- | -------------------------- |
| `{nas}-{type}` | `truenas-movies`  | Static PVC bound to NAS PV |
| `{app}-config` | `sonarr-config`   | Dynamic PVC for app config |
| `{app}-data`   | `postgresql-data` | Database storage           |

## Variable Substitution

Storage files use Flux postBuild substitution from `clusters/catalyst-cluster/cluster-settings.yaml`:

```yaml
# cluster-settings.yaml
data:
  TRUENAS_IP: '192.168.1.200'
  TRUENAS_POOL: '/mnt/megapool'
  SYNOLOGY_IP: '192.168.1.234'
  SYNOLOGY_VOLUME: '/volume1'
```

These variables are substituted in storage manifests:

```yaml
nfs:
  server: '${TRUENAS_IP}'
  path: '${TRUENAS_POOL}/media/movies'
```

## Files

| File                          | Description                             |
| ----------------------------- | --------------------------------------- |
| `local-path-provisioner.yaml` | Local path storage class (default)      |
| `truenas-storage.yaml`        | TrueNAS PVs, PVCs, and storage class    |
| `synology-storage.yaml`       | Synology PVs, PVCs, and storage class   |
| `nfs-provisioner/`            | Dynamic NFS provisioner for app configs |
