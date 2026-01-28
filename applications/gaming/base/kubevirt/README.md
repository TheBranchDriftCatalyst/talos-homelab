# KubeVirt Windows Gaming VM

Windows VM for running game servers like Conan Exiles Dedicated Server.

## Quick Start

```bash
# 1. Apply the manifests
kubectl apply -k applications/gaming/base/kubevirt/ -n gaming

# 2. Upload ISOs (see below)

# 3. Start the VM
virtctl start windows-gameserver -n gaming

# 4. Access via VNC
# Web: http://windows-vnc.talos00 (add to /etc/hosts)
# CLI: virtctl vnc windows-gameserver -n gaming
```

## Required ISOs

### Windows 11 ISO
Download from Microsoft and upload:
```bash
# Port forward CDI upload proxy
kubectl port-forward -n cdi svc/cdi-uploadproxy 8443:443 &

# Create DataVolume and upload (windows-iso DV already in manifests)
virtctl image-upload dv windows-iso \
  --image-path=/path/to/Win11_23H2_English_x64v2.iso \
  -n gaming \
  --insecure \
  --uploadproxy-url=https://localhost:8443 \
  --no-create
```

### VirtIO Drivers ISO
Required for Windows to see the virtual disk:
```bash
# Download
curl -L -o /tmp/virtio-win.iso https://fedorapeople.org/groups/virt/virtio-win/direct-downloads/stable-virtio/virtio-win.iso

# Upload
virtctl image-upload dv virtio-drivers \
  --image-path=/tmp/virtio-win.iso \
  -n gaming \
  --insecure \
  --uploadproxy-url=https://localhost:8443 \
  --no-create
```

## Windows 11 Installation

### Bypass TPM/Secure Boot Check
When you see "This PC can't run Windows 11":

1. Press **Shift + F10** to open Command Prompt
2. Run these commands:
```cmd
reg add HKLM\SYSTEM\Setup\LabConfig /v BypassTPMCheck /t REG_DWORD /d 1
reg add HKLM\SYSTEM\Setup\LabConfig /v BypassSecureBootCheck /t REG_DWORD /d 1
reg add HKLM\SYSTEM\Setup\LabConfig /v BypassRAMCheck /t REG_DWORD /d 1
```
3. Close Command Prompt and click the back arrow, then proceed

### Load VirtIO Storage Driver
When you see "Where do you want to install Windows?" with no drives:

1. Click **Load driver**
2. Click **Browse**
3. Navigate to the VirtIO CD-ROM drive
4. Select: `viostor\w11\amd64`
5. Click **OK** and select the "Red Hat VirtIO SCSI controller"
6. The 150GB drive should now appear

## Access Methods

| Method | URL/Command |
|--------|-------------|
| Web VNC | http://windows-vnc.talos00 |
| CLI VNC | `virtctl vnc windows-gameserver -n gaming` |
| RDP (after install) | `192.168.1.54:30389` |

## Port Mapping

| Service | Container Port | NodePort | Router Forward |
|---------|---------------|----------|----------------|
| RDP | 3389/TCP | 30389 | 3389 → :30389 |
| Conan Game | 27101/UDP | 31101 | 27101 → :31101 |
| Conan Raw | 27102/UDP | 31102 | 27102 → :31102 |
| Steam Query | 27015/UDP | 31015 | 27015 → :31015 |
| RCON | 27104/TCP | 31104 | 27104 → :31104 |

## VM Management

```bash
# Start VM
virtctl start windows-gameserver -n gaming

# Stop VM
virtctl stop windows-gameserver -n gaming

# Restart VM
virtctl restart windows-gameserver -n gaming

# Console access
virtctl console windows-gameserver -n gaming

# Check status
kubectl get vm,vmi -n gaming
```

## Troubleshooting

### PVC Node Affinity Issues
All PVCs must be on the same node. If the VM won't start:
```bash
# Check node bindings
for pvc in windows-gameserver-disk windows-iso virtio-drivers; do
  PV=$(kubectl get pvc -n gaming $pvc -o jsonpath='{.spec.volumeName}')
  NODE=$(kubectl get pv $PV -o jsonpath='{.spec.nodeAffinity.required.nodeSelectorTerms[0].matchExpressions[0].values[0]}')
  echo "$pvc -> $NODE"
done
```

### Recreate PVC on Specific Node
```bash
# Delete the misplaced PVC
kubectl delete dv -n gaming <name>

# Create binder pod on correct node
kubectl run pvc-binder -n gaming --image=busybox \
  --overrides='{"spec":{"nodeSelector":{"kubernetes.io/hostname":"talos06"}}}' \
  --restart=Never -- sleep infinity

# After PVC binds, delete the binder
kubectl delete pod -n gaming pvc-binder
```

## Files

| File | Purpose |
|------|---------|
| windows-vm.yaml | VM definition + boot disk PVC |
| windows-service.yaml | NodePort services for RDP and game ports |
| virtio-drivers-dv.yaml | DataVolume for VirtIO drivers ISO |
| novnc.yaml | Web-based VNC console |
