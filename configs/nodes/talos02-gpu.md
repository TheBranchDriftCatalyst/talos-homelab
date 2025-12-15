# talos02-gpu - Intel Arc GPU Worker Node

## Status: PENDING NODE BOOT

**Beads Epic**: TALOS-fpp

## Hardware Specifications

| Spec        | Value                                |
| ----------- | ------------------------------------ |
| **Model**   | ASUS NUC 15 Pro (RNUC15U5)           |
| **CPU**     | Intel Core Ultra 5 225H (Arrow Lake) |
| **GPU**     | Intel Arc (integrated Xe2 graphics)  |
| **Year**    | 2025                                 |
| **Purpose** | GPU transcoding workhorse            |

## Network Configuration

| Setting         | Value                                    |
| --------------- | ---------------------------------------- |
| **Hostname**    | talos02-gpu                              |
| **Expected IP** | 192.168.1.XXX (DHCP - update when known) |
| **Node Role**   | Worker                                   |

## Progress Tracking

| Task                                  | Status  | Beads ID  |
| ------------------------------------- | ------- | --------- |
| Config directory reorganization       | DONE    | TALOS-wbb |
| GPU worker config created             | DONE    | TALOS-2b2 |
| Image Factory schematic               | DONE    | TALOS-akv |
| Flux infrastructure (NFD + Intel GPU) | DONE    | TALOS-34t |
| Boot node with custom image           | PENDING | TALOS-y1c |
| Verify GPU device & labels            | BLOCKED | TALOS-dfv |
| Configure Plex/Tdarr                  | BLOCKED | TALOS-9ku |

## GPU Configuration

### Talos Requirements

This node requires a **custom Talos image** with the following extensions:

- `siderolabs/i915` - Intel GPU firmware and kernel modules
- `siderolabs/intel-ucode` - Intel CPU microcode updates

**Generate Image:**

```bash
# Get schematic ID
curl -X POST --data-binary @configs/nodes/talos02-gpu-schematic.yaml \
  https://factory.talos.dev/schematics

# Download ISO (replace <SCHEMATIC_ID>)
# https://factory.talos.dev/image/<SCHEMATIC_ID>/v1.11.1/metal-amd64.iso
```

### Kernel Driver

The Intel Core Ultra 5 225H uses the newer **Xe2 architecture**, which requires:

- **Kernel driver**: `xe` (new upstream driver for Xe2+)
- **Fallback**: `i915` for older Intel GPUs

Both modules are configured to load in `worker-talos02-gpu.yaml`.

### Device Access

GPU will be exposed via:

- `/dev/dri/card0` - DRM device
- `/dev/dri/renderD128` - Render node (used by applications)

### Kubernetes Labels (Applied by NFD)

```yaml
intel.feature.node.kubernetes.io/gpu: 'true'
gpu.intel.com/device-id.present: 'true'
node-role.kubernetes.io/gpu-worker: '' # Pre-configured in machine config
node.kubernetes.io/workload-type: media-transcoding # Pre-configured
```

## Workload Affinity

This node is the **priority target** for:

- **Plex** - Hardware transcoding (QSV/VA-API)
- **Tdarr** - Video encoding/transcoding
- **Jellyfin** - Alternative media server
- Any GPU-accelerated workloads

### Pod Configuration Example

```yaml
spec:
  nodeSelector:
    intel.feature.node.kubernetes.io/gpu: 'true'
  containers:
    - name: plex
      resources:
        limits:
          gpu.intel.com/i915: '1'
        requests:
          gpu.intel.com/i915: '1'
      volumeMounts:
        - name: dri
          mountPath: /dev/dri
  volumes:
    - name: dri
      hostPath:
        path: /dev/dri
        type: Directory
```

## Setup Checklist

- [x] Generate custom Talos image schematic (`talos02-gpu-schematic.yaml`)
- [x] Create machine config (`worker-talos02-gpu.yaml`)
- [x] Create Flux infrastructure (`infrastructure/base/intel-gpu/`)
- [ ] Boot node with Talos ISO
- [ ] Update config with actual IP address
- [ ] Apply machine config (`talosctl apply-config`)
- [ ] Verify GPU device exists (`/dev/dri/renderD128`)
- [ ] Verify NFD labels applied
- [ ] Verify `gpu.intel.com/i915` in node allocatable
- [ ] Test GPU workload scheduling

## Files Created

| File                                       | Purpose                             |
| ------------------------------------------ | ----------------------------------- |
| `configs/nodes/worker-talos02-gpu.yaml`    | Machine configuration               |
| `configs/nodes/talos02-gpu-schematic.yaml` | Image Factory schematic             |
| `configs/nodes/talos02-gpu.md`             | This documentation                  |
| `infrastructure/base/intel-gpu/`           | Flux-managed NFD + Intel GPU plugin |
| `clusters/catalyst-cluster/intel-gpu.yaml` | Flux Kustomization                  |

## References

- [Intel GPU Device Plugin](https://intel.github.io/intel-device-plugins-for-kubernetes/cmd/gpu_plugin/README.html)
- [Talos Image Factory](https://factory.talos.dev)
- [Intel Arc on Kubernetes (Feb 2025)](https://jonathangazeley.com/2025/02/11/intel-gpu-acceleration-on-kubernetes/)
- [Talos GPU Discussion](https://github.com/siderolabs/talos/discussions/7026)

---

## Related Issues

- TALOS-fpp - Epic: Set up talos02-gpu worker node with Intel Arc
- TALOS-y1c - Boot talos02-gpu with custom Talos image (NEXT)
- TALOS-dfv - Verify GPU device and NFD labels
- TALOS-9ku - Configure Plex/Tdarr for GPU transcoding
