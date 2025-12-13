# Intel GPU Support for Kubernetes

This directory contains the infrastructure components needed to enable Intel GPU access in Kubernetes workloads.

## Components

### 1. Node Feature Discovery (NFD)

Auto-detects hardware features on all nodes and applies labels.

**Deployment:**
```bash
# Add Helm repo
helm repo add nfd https://kubernetes-sigs.github.io/node-feature-discovery/charts
helm repo update

# Install NFD
helm upgrade -i node-feature-discovery nfd/node-feature-discovery \
  --namespace node-feature-discovery \
  --create-namespace \
  --values infrastructure/base/intel-gpu/nfd-values.yaml
```

### 2. Intel GPU Device Plugin

Exposes Intel GPU resources to Kubernetes scheduler.

**Deployment:**
```bash
# Add Intel Helm repo
helm repo add intel https://intel.github.io/helm-charts
helm repo update

# Install Intel Device Plugins Operator
helm upgrade -i intel-device-plugins-operator intel/intel-device-plugins-operator \
  --namespace intel-device-plugins \
  --create-namespace

# Deploy GPU plugin
kubectl apply -f infrastructure/base/intel-gpu/gpu-device-plugin.yaml
```

## Verification

### Check NFD Labels
```bash
kubectl get nodes -o json | jq '.items[].metadata.labels | with_entries(select(.key | startswith("feature.node.kubernetes.io") or startswith("intel.feature")))'
```

### Check GPU Resources
```bash
kubectl get nodes -o json | jq '.items[] | {name: .metadata.name, gpu: .status.allocatable["gpu.intel.com/i915"]}'
```

### Verify GPU Device
```bash
# On the GPU node via talosctl
talosctl -n <GPU_NODE_IP> ls /dev/dri
```

Expected output:
```
card0
renderD128
```

## Pod Configuration

To use the GPU in a pod:

```yaml
apiVersion: v1
kind: Pod
metadata:
  name: gpu-test
spec:
  containers:
  - name: gpu-test
    image: intel/intel-gpu-tools:latest
    command: ["intel_gpu_top", "-l"]
    resources:
      limits:
        gpu.intel.com/i915: "1"
    securityContext:
      capabilities:
        add: ["SYS_RAWIO"]  # Only needed for intel_gpu_top
  nodeSelector:
    intel.feature.node.kubernetes.io/gpu: "true"
```

## Troubleshooting

### GPU Not Detected
1. Verify custom Talos image includes `siderolabs/i915` extension
2. Check for `/dev/dri/renderD128` on the node
3. Check NFD logs: `kubectl logs -n node-feature-discovery -l app=nfd-master`

### Pods Not Scheduling
1. Check node has `gpu.intel.com/i915` in allocatable resources
2. Verify Intel GPU plugin pod is running
3. Check device plugin logs: `kubectl logs -n intel-device-plugins -l app=intel-gpu-plugin`

## References

- [Intel Device Plugins for Kubernetes](https://intel.github.io/intel-device-plugins-for-kubernetes/)
- [Node Feature Discovery](https://kubernetes-sigs.github.io/node-feature-discovery/)
- [Intel GPU Plugin README](https://github.com/intel/intel-device-plugins-for-kubernetes/blob/main/cmd/gpu_plugin/README.md)
