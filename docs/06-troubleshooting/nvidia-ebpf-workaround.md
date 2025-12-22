# NVIDIA GPU + Talos Linux Kernel 6.12 eBPF Workaround

## TL;DR

NVIDIA containers fail on Talos Linux with kernel 6.12 due to an eBPF cgroup device filter bug in `nvidia-container-toolkit`. This document describes the **working CDI workaround**.

**Status**: ✅ **RESOLVED** - NVENC hardware encoding working via CDI with hook binary patch

**Solution Summary**:
1. Configure containerd to use `nvidia-cdi` runtime
2. Generate CDI spec with `nvidia-ctk cdi generate`
3. Deploy DaemonSet to copy CDI spec AND patch hook paths to use `.real` binaries

**Affected Components**:
- talos05 (192.168.1.194) - NVIDIA Quadro P2000
- tdarr-node-gpu-talos05 deployment
- Kernel: 6.12.45-talos
- nvidia-container-toolkit from Talos extension

---

## Root Cause

Two separate issues were discovered:

### Issue 1: eBPF Cgroup Device Filter Bug
The nvidia-container-toolkit uses eBPF cgroup device filters to manage GPU device access. Kernel 6.12 introduced changes to the eBPF verifier that break the device filter program generation.

**Error Message**:
```
nvidia-container-cli: mount error: failed to add device rules:
unable to generate new device filter program from existing programs:
unable to create new device filters program: load program: invalid argument:
last insn is not an exit or jmp
```

### Issue 2: Talos nvidia-container-runtime-wrapper Command Dispatch
The Talos nvidia-container-toolkit extension uses wrapper scripts that dispatch commands based on `argv[0]`. The wrapper doesn't recognize `nvidia-cdi-hook` as a valid command, causing CDI hooks to fail with exit code 1.

**Error Message**:
```
nvidia-container-runtime-wrapper: unknown command nvidia-cdi-hook
```

**Solution**: Use `.real` binaries directly (e.g., `nvidia-cdi-hook.real`) to bypass the wrapper.

**Related Issues**:
- [libnvidia-container#176](https://github.com/NVIDIA/libnvidia-container/issues/176)
- Affects kernel 6.12+ with nvidia-container-toolkit

---

## Environment

```yaml
Node: talos05
IP: 192.168.1.194
GPU: NVIDIA Quadro P2000 (passthrough from Proxmox/Incus)
Talos Version: v1.11.1
Kernel: 6.12.45-talos
containerd: 2.1.4
Driver Version: 535.247.01
VRAM: 5120 MiB

Extensions:
  - siderolabs/nvidia-container-toolkit
  - siderolabs/nonfree-kmod-nvidia

Verified Working:
  - h264_nvenc: 5.69x realtime
  - hevc_nvenc: 5.24x realtime
```

---

## Solution: CDI with Hook Binary Patch

### Overview

CDI (Container Device Interface) is the modern approach for GPU device injection that doesn't use eBPF cgroup hooks. However, the Talos extension's wrapper scripts don't recognize CDI hook commands. The solution patches the CDI spec to use `.real` binaries directly.

### Step 1: Talos Machine Configuration

Modified `configs/talos05-nvgpu/worker-talos05.yaml`:

```yaml
machine:
  # NVIDIA kernel modules
  kernel:
    modules:
      - name: nvidia
      - name: nvidia_uvm
      - name: nvidia_drm
      - name: nvidia_modeset

  # udev rules for NVIDIA device permissions
  udev:
    rules:
      - SUBSYSTEM=="drm", KERNEL=="renderD*", GROUP="44", MODE="0660"
      - SUBSYSTEM=="drm", KERNEL=="card*", GROUP="44", MODE="0660"
      - KERNEL=="nvidia", MODE="0666"
      - KERNEL=="nvidia_uvm", MODE="0666"
      - KERNEL=="nvidia-uvm-tools", MODE="0666"
      - KERNEL=="nvidia-modeset", MODE="0666"
      - KERNEL=="nvidiactl", MODE="0666"

  # Node labels for GPU workload scheduling
  nodeLabels:
    node.kubernetes.io/gpu-vendor: nvidia

  # containerd CDI configuration
  files:
    - content: |
        [plugins]
          [plugins."io.containerd.cri.v1.runtime"]
            cdi_spec_dirs = ["/etc/cdi", "/var/run/cdi", "/var/cdi"]
            [plugins."io.containerd.cri.v1.runtime".containerd]
              default_runtime_name = "nvidia-cdi"
            [plugins."io.containerd.cri.v1.runtime".containerd.runtimes.nvidia-cdi]
              runtime_type = "io.containerd.runc.v2"
              [plugins."io.containerd.cri.v1.runtime".containerd.runtimes.nvidia-cdi.options]
                BinaryName = "/usr/local/bin/nvidia-container-runtime.cdi"
      path: /etc/cri/conf.d/20-customization.part
      op: create
    - content: ""
      path: /var/cdi/.keep
      op: create
    - content: ""
      path: /var/run/cdi/.keep
      op: create
```

### Step 2: Generate CDI Spec (One-time)

Run a privileged pod with nsenter to execute nvidia-ctk on the host:

```bash
cat <<'EOF' | kubectl apply -f -
apiVersion: v1
kind: Pod
metadata:
  name: nvidia-cdi-generator
  namespace: kube-system
spec:
  nodeSelector:
    kubernetes.io/hostname: talos05
  restartPolicy: Never
  hostPID: true
  hostNetwork: true
  containers:
  - name: generator
    image: alpine:latest
    command:
    - /bin/sh
    - -c
    - |
      apk add --no-cache util-linux
      nsenter -t 1 -m -u -n -i sh -c "mkdir -p /var/cdi && /usr/local/bin/nvidia-ctk cdi generate --output=/var/cdi/nvidia.yaml"
      echo "CDI spec generated. Verify with:"
      echo "  talosctl -n 192.168.1.194 read /var/cdi/nvidia.yaml | head -50"
    securityContext:
      privileged: true
EOF

# Wait for completion
kubectl wait --for=condition=Ready pod/nvidia-cdi-generator -n kube-system --timeout=60s || true
kubectl logs -n kube-system nvidia-cdi-generator
kubectl delete pod -n kube-system nvidia-cdi-generator
```

### Step 3: Deploy CDI Init DaemonSet

The DaemonSet copies the CDI spec to `/var/run/cdi` AND patches hook paths to use `.real` binaries:

```yaml
# infrastructure/base/nvidia-cdi/nvidia-cdi-init.yaml
apiVersion: apps/v1
kind: DaemonSet
metadata:
  name: nvidia-cdi-init
  namespace: kube-system
  labels:
    app: nvidia-cdi-init
spec:
  selector:
    matchLabels:
      app: nvidia-cdi-init
  template:
    metadata:
      labels:
        app: nvidia-cdi-init
    spec:
      nodeSelector:
        node.kubernetes.io/gpu-vendor: nvidia
      hostPID: true
      tolerations:
      - key: "nvidia.com/gpu"
        operator: "Exists"
        effect: "NoSchedule"
      initContainers:
      - name: copy-cdi-spec
        image: alpine:latest
        command:
        - /bin/sh
        - -c
        - |
          echo "=== NVIDIA CDI Spec Initializer ==="
          mkdir -p /var-run-cdi

          if [ -f /var-cdi/nvidia.yaml ]; then
            cp /var-cdi/nvidia.yaml /var-run-cdi/
            echo "CDI spec copied successfully"

            # WORKAROUND: Talos nvidia-container-runtime-wrapper doesn't recognize
            # nvidia-cdi-hook command. Use .real binary directly to bypass wrapper.
            echo "Patching CDI spec to use nvidia-cdi-hook.real..."
            sed -i 's|/usr/local/bin/nvidia-cdi-hook|/usr/local/bin/nvidia-cdi-hook.real|g' /var-run-cdi/nvidia.yaml

            echo "Devices in spec:"
            grep "^  name:" /var-run-cdi/nvidia.yaml || true
            echo "Hook paths patched to use .real binaries"
          else
            echo "ERROR: CDI spec not found at /var/cdi/nvidia.yaml"
            echo "Generate it with: nvidia-ctk cdi generate --output=/var/cdi/nvidia.yaml"
            exit 1
          fi
        securityContext:
          privileged: true
        volumeMounts:
        - name: var-cdi
          mountPath: /var-cdi
          readOnly: true
        - name: var-run-cdi
          mountPath: /var-run-cdi
      containers:
      - name: pause
        image: registry.k8s.io/pause:3.9
        resources:
          requests:
            cpu: "1m"
            memory: "4Mi"
      volumes:
      - name: var-cdi
        hostPath:
          path: /var/cdi
          type: DirectoryOrCreate
      - name: var-run-cdi
        hostPath:
          path: /var/run/cdi
          type: DirectoryOrCreate
```

Apply with:
```bash
kubectl apply -f infrastructure/base/nvidia-cdi/nvidia-cdi-init.yaml
```

---

## Verification

### Check CDI Init Pod
```bash
kubectl get pods -n kube-system -l app=nvidia-cdi-init
kubectl logs -n kube-system -l app=nvidia-cdi-init -c copy-cdi-spec
```

### Verify Patched CDI Spec
```bash
# Should show .real paths
talosctl -n 192.168.1.194 read /var/run/cdi/nvidia.yaml | grep "path:" | grep hook
```

Expected output:
```
    path: /usr/local/bin/nvidia-cdi-hook.real
```

### Test NVENC Encoding
```bash
kubectl exec -n media deploy/tdarr-node-gpu-talos05 -- bash -c '
nvidia-smi --query-gpu=name,driver_version,memory.total --format=csv
ffmpeg -hide_banner -hwaccel cuda -f lavfi -i testsrc=duration=2:size=1280x720:rate=30 \
  -c:v hevc_nvenc -preset fast -f null - 2>&1 | tail -5
'
```

Expected output:
```
name, driver_version, memory.total [MiB]
Quadro P2000, 535.247.01, 5120 MiB
frame=   60 fps=0.0 q=9.0 Lsize=N/A time=00:00:01.96 bitrate=N/A speed=5.24x
```

---

## Files

| File | Purpose |
|------|---------|
| `configs/talos05-nvgpu/worker-talos05.yaml` | Talos machine config with CDI settings |
| `infrastructure/base/nvidia-cdi/nvidia-cdi-init.yaml` | DaemonSet to copy and patch CDI spec |
| `applications/arr-stack/base/tdarr/tdarr-node-gpu-talos05.yaml` | Tdarr GPU worker deployment |

---

## Commands Reference

```bash
# Apply Talos config (triggers reboot)
talosctl -n 192.168.1.194 apply-config --file configs/talos05-nvgpu/worker-talos05.yaml

# Check node status
kubectl get node talos05 -o wide

# Generate CDI spec (one-time)
# See Step 2 above

# Check CDI spec
talosctl -n 192.168.1.194 read /var/run/cdi/nvidia.yaml | head -50

# Verify hook paths are patched
talosctl -n 192.168.1.194 read /var/run/cdi/nvidia.yaml | grep "nvidia-cdi-hook"

# Check containerd config
talosctl -n 192.168.1.194 read /etc/cri/conf.d/20-customization.part

# Test NVENC
kubectl exec -n media deploy/tdarr-node-gpu-talos05 -- \
  ffmpeg -hwaccel cuda -f lavfi -i testsrc=duration=2:size=1920x1080:rate=30 \
  -c:v hevc_nvenc -preset fast -f null -
```

---

## Troubleshooting

### "unresolvable CDI devices nvidia.com/gpu=all"
- CDI spec not found in `/var/run/cdi/`
- Check nvidia-cdi-init DaemonSet is running
- Verify CDI spec exists: `talosctl -n <node> list /var/run/cdi/`

### "nvidia-container-runtime-wrapper: unknown command nvidia-cdi-hook"
- CDI spec hook paths not patched to use `.real` binaries
- Restart nvidia-cdi-init DaemonSet: `kubectl rollout restart ds/nvidia-cdi-init -n kube-system`
- Verify: `talosctl -n <node> read /var/run/cdi/nvidia.yaml | grep nvidia-cdi-hook.real`

### Container still fails after fix
- Restart the workload: `kubectl rollout restart deployment/<name> -n <namespace>`
- CDI spec is read at container creation time, not dynamically

---

## Related Issues

- TALOS-oik1: Kubernetes Device Plugins (Intel, NFD, smarter-device-manager)
