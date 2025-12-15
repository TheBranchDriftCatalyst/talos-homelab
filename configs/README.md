# Talos Configuration Directory

This directory contains all Talos Linux machine configurations and related files.

## Directory Structure

```
configs/
├── README.md              # This file
├── talosconfig            # Talos CLI configuration (endpoints, auth)
├── cilium-values.yaml     # Cilium CNI Helm values
├── cilium-manifest.yaml   # Generated Cilium manifests
├── nodes/                 # Per-node machine configurations
│   ├── controlplane.yaml  # talos00 - Control plane node
│   ├── worker-base.yaml   # Base worker template (unused)
│   ├── worker-talos01.yaml # talos01 - Worker node (observability)
│   └── talos02-gpu.md     # talos02-gpu - GPU worker documentation
└── patches/               # Reusable configuration patches
    └── (future patches)
```

## Node Inventory

| Node        | Role          | IP            | Purpose                       | Special Config |
| ----------- | ------------- | ------------- | ----------------------------- | -------------- |
| talos00     | Control Plane | 192.168.1.54  | Cluster control, workloads    | -              |
| talos01     | Worker        | 192.168.1.177 | Observability workloads       | NVMe disk      |
| talos02-gpu | Worker        | TBD           | GPU transcoding (Plex, Tdarr) | Intel Arc GPU  |

## Configuration Patterns

### Machine Types

- **controlplane.yaml** - Full cluster config including secrets, etcd, API server settings
- **worker-\*.yaml** - Worker configs inherit cluster identity but exclude control plane specifics

### Common Customizations

Each node config typically includes:

- `machine.network.hostname` - Unique hostname
- `machine.install.disk` - Node-specific boot disk
- `machine.kubelet.nodeIP.validSubnets` - Force LAN IP for Prometheus
- `machine.nodeLabels` - Role-based labels for scheduling

### Patches Directory

Use `patches/` for reusable configuration snippets:

```bash
# Apply patch to existing config
talosctl machineconfig patch configs/nodes/worker-talos01.yaml --patch @configs/patches/gpu.yaml
```

## Workflow

### Generate New Node Config

```bash
# Generate worker config from secrets
talosctl gen config catalyst-cluster https://192.168.1.54:6443 \
  --output-types worker \
  --with-secrets configs/secrets.yaml \
  --output configs/nodes/worker-newnode.yaml
```

### Apply Configuration

```bash
# Apply to specific node
talosctl apply-config -n 192.168.1.XXX -f configs/nodes/worker-newnode.yaml

# With insecure mode (first-time setup)
talosctl apply-config -n 192.168.1.XXX -f configs/nodes/worker-newnode.yaml --insecure
```

### Validate Configuration

```bash
talosctl validate -m metal -c configs/nodes/controlplane.yaml
```

## Security Notes

- Machine configs contain cluster secrets - treat as sensitive
- `talosconfig` contains admin credentials
- These files are gitignored by default (check `.gitignore`)
