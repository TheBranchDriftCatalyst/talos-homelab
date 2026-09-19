# Storage Architecture

This document describes the storage mount structure for the homelab cluster.

## Overview

The cluster uses **one** NAS for storage:

- **Synology** (`${SYNOLOGY_IP}` = `192.168.1.36`) — media libraries, downloads and app
  configuration. Everything was migrated here.
- **TrueNAS** (192.168.1.200) — decommissioned. `truenas-storage.yaml` has been deleted and
  `TRUENAS_IP` / `TRUENAS_POOL` are no longer defined in `cluster-settings.yaml`, so no
  `truenas-*` PV, PVC or StorageClass exists any more.

All NFS variables are substituted via Flux postBuild from `cluster-settings.yaml`.

## Storage Classes

| Storage Class          | Type              | Use Case                                   |
| ---------------------- | ----------------- | ------------------------------------------ |
| `local-path` (default) | Local provisioner | Databases, pods needing fast local storage |
| `synology-nfs`         | Static NFS        | Media libraries, downloads                 |
| `fatboy-nfs-appdata`   | Dynamic NFS       | App configs (\*arr apps)                   |

## NAS Mount Structure

All paths below are on the Synology, exported under `${SYNOLOGY_VOLUME}` (`/volume1`) from
`${SYNOLOGY_IP}` (`192.168.1.36`). Static PVs and PVCs are declared in `synology-storage.yaml`.

### Static media / downloads PVs

| NFS path                        | PersistentVolume                | Bound PVC                       | Capacity |
| ------------------------------- | ------------------------------- | ------------------------------- | -------- |
| `/volume1/media/movies`         | `synology-media-movies`         | `synology-movies`               | 30Ti     |
| `/volume1/media/tv`             | `synology-media-tv`             | `synology-tv`                   | 30Ti     |
| `/volume1/media/books`          | `synology-media-books`          | `synology-books`                | 500Gi    |
| `/volume1/downloads/complete`   | `synology-downloads-complete`   | `synology-downloads-complete`   | 1Ti      |
| `/volume1/downloads/incomplete` | `synology-downloads-incomplete` | `synology-downloads-incomplete` | 500Gi    |

`/volume1/media/music` is **not** provisioned: the `synology-media-music` PV and
`synology-music` PVC are commented out in `synology-storage.yaml`.

### Dynamically provisioned app config

| NFS path           | StorageClass         | Provisioner                       |
| ------------------ | -------------------- | --------------------------------- |
| `/volume1/appdata` | `fatboy-nfs-appdata` | `nfs-subdir-external-provisioner` |

Each `<app>-config` PVC gets its own subdirectory under `/volume1/appdata` — the provisioner
creates them, they are not declared here.

### TrueNAS (decommissioned)

The former TrueNAS mounts under `/mnt/megapool/{media,downloads}` and the `truenas-media-*` /
`truenas-downloads-*` PVs no longer exist in this repo.

## App Storage Pattern

### Media Apps (\*arr stack)

Each media app gets:

1. **Config volume** - Dynamic PVC using `fatboy-nfs-appdata` (Synology /volume1/appdata/)
2. **Media volume(s)** - Static PVC(s) bound to the Synology media PVs
3. **Downloads volume** - Static PVC bound to downloads PV

Example for Sonarr:

```yaml
volumes:
  - name: config
    persistentVolumeClaim:
      claimName: sonarr-config # Dynamic, fatboy-nfs-appdata
  - name: media-tv
    persistentVolumeClaim:
      claimName: synology-tv # Static, Synology
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
| `{nas}-{type}` | `synology-movies` | Static PVC bound to NAS PV |
| `{app}-config` | `sonarr-config`   | Dynamic PVC for app config |
| `{app}-data`   | `postgresql-data` | Database storage           |

## Variable Substitution

Storage files use Flux postBuild substitution from `clusters/catalyst-cluster/cluster-settings.yaml`:

```yaml
# cluster-settings.yaml
data:
  SYNOLOGY_IP: '192.168.1.36'
  SYNOLOGY_VOLUME: '/volume1'
```

These variables are substituted in storage manifests:

```yaml
nfs:
  server: '${SYNOLOGY_IP}'
  path: '${SYNOLOGY_VOLUME}/media/movies'
```

## Files

| File                          | Description                             |
| ----------------------------- | --------------------------------------- |
| `local-path-provisioner.yaml` | Local path storage class (default)      |
| `synology-storage.yaml`       | Synology PVs, PVCs, and storage class   |
| `nfs-provisioner/`            | Dynamic NFS provisioner for app configs |
| `tests/`                      | pytest checks for this stack            |
