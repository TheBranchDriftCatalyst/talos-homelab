# Tilt Pre-Flight Check - First Startup

**Date:** 2025-11-25
**Status:** ⚠️ READY WITH WARNINGS
**Purpose:** Verify existing Tilt setup against current Flux-managed cluster state

---

## ✅ Pre-Flight Check Results

### 1. Tilt Installation
- ✅ **Tilt Installed:** v0.36.0 (built 2025-11-18)
- ✅ **Location:** `/opt/homebrew/bin/tilt`
- ✅ **Version:** Latest stable

### 2. Kubernetes Context
- ⚠️ **Current Context:** `admin@homelab-single`
- ⚠️ **Tiltfile Expects:** `kubernetes-admin@talos00`
- **Action Required:** Update Tiltfiles or switch context

**Context Mismatch Details:**
```bash
# Current context
$ kubectl config current-context
admin@homelab-single

# Tiltfiles expect
allow_k8s_contexts('kubernetes-admin@talos00')
```

### 3. Flux Status
- ✅ **Flux Running:** Yes
- ✅ **Flux Healthy:** All kustomizations ready
- ✅ **Current Revision:** `main@sha1:6fab3206`
- ✅ **Suspended:** False (Flux is actively reconciling)

**Flux Kustomizations:**
```
NAME       	REVISION          	SUSPENDED	READY	MESSAGE
flux-system	main@sha1:6fab3206	False    	True 	Applied revision: main@sha1:6fab3206
```

### 4. Existing Cluster Resources

#### Infrastructure Resources (Flux-Managed)
- ✅ **monitoring:** kube-prometheus-stack, prometheus-blackbox-exporter
- ✅ **observability:** fluent-bit, graylog, mongodb, opensearch
- ✅ **external-secrets:** external-secrets-operator
- ✅ **kube-system:** nfs-subdir-external-provisioner

#### Namespace Status
- ✅ **media-prod:** EXISTS (13 workloads running - Flux-managed)
- ⚠️ **media-dev:** DOES NOT EXIST (Tilt will create it)
- ✅ **monitoring:** EXISTS (Flux-managed)
- ✅ **observability:** EXISTS (Flux-managed)
- ✅ **infra-testing:** EXISTS (Flux-managed)

---

## ⚠️ CRITICAL ISSUES TO ADDRESS

### Issue #1: Kubernetes Context Mismatch

**Problem:** Root Tiltfile expects `kubernetes-admin@talos00`, but current context is `admin@homelab-single`.

**Impact:** Tilt will fail to start with context validation error.

**Solutions:**

**Option A: Update Tiltfiles** (Recommended)
```bash
# Update all three Tiltfiles
sed -i '' 's/kubernetes-admin@talos00/admin@homelab-single/g' Tiltfile
sed -i '' 's/kubernetes-admin@talos00/admin@homelab-single/g' infrastructure/Tiltfile
sed -i '' 's/kubernetes-admin@talos00/admin@homelab-single/g' applications/arr-stack/Tiltfile
```

**Option B: Switch kubectl context**
```bash
# Check available contexts
kubectl config get-contexts

# Switch to talos00 context if it exists
kubectl config use-context kubernetes-admin@talos00
```

---

### Issue #2: Flux Suspension Strategy

**Problem:** Tilt will suspend Flux by default, but your cluster is actively managed by Flux.

**Current Tilt Behavior:**
```python
# Root Tiltfile line 34
'flux_suspend': cfg.get('flux-suspend', True),  # Defaults to suspending Flux

# Line 62
if settings['flux_suspend']:
    local('flux suspend kustomization flux-system')
```

**Impact:**
- Tilt will suspend Flux reconciliation on startup
- Your Flux-managed resources will stop auto-updating
- Manual resume required if Tilt crashes

**Recommendations:**

**For Initial Testing:** Keep suspension enabled
- Prevents Flux from fighting Tilt during development
- Manual control over reconciliation
- Use `flux-resume-all` button in Tilt UI when needed

**For Daily Use:** Disable suspension
```bash
# Start Tilt without suspending Flux
SUSPEND_FLUX=false tilt up

# Or set in config
tilt config set flux-suspend false
```

---

### Issue #3: Resource Conflicts

**Problem:** Tilt expects to manage resources that Flux already controls.

**Affected Resources:**
- monitoring:prometheus (Flux HelmRelease `kube-prometheus-stack`)
- monitoring:grafana (part of kube-prometheus-stack)
- monitoring:alertmanager (part of kube-prometheus-stack)
- observability:graylog (Flux HelmRelease `graylog`)
- observability:opensearch (Flux HelmRelease `opensearch`)
- observability:fluent-bit (Flux HelmRelease `fluent-bit`)

**Current Tilt Setup:** k8s_attach pattern (monitoring only, not deploying)
```python
# Root Tiltfile lines 223-257
k8s_resource(
    workload='prometheus-kube-prometheus-stack-prometheus',
    new_name='monitoring:prometheus',
    port_forwards=['9090:9090'],
    labels=['monitoring']
)
```

**Analysis:** ✅ **SAFE**
- Tilt is only *attaching* to existing resources (not deploying)
- Provides monitoring and port-forwarding
- No conflict with Flux management

---

### Issue #4: Media Stack Namespace Mismatch

**Problem:** Arr-stack Tiltfile targets `media-dev` but production is in `media-prod`.

**Current State:**
- `media-prod` namespace: ✅ EXISTS (13 workloads, Flux-managed)
- `media-dev` namespace: ❌ DOES NOT EXIST

**Arr-Stack Tiltfile:**
```python
# applications/arr-stack/Tiltfile line 13
namespace = 'media-dev'

# Line 28
k8s_yaml(kustomize('overlays/dev'))
```

**Analysis:** ✅ **INTENTIONAL & SAFE**
- Tilt is designed for dev environment (`media-dev`)
- Production environment (`media-prod`) managed by Flux
- No conflict - separate namespaces for dev/prod

---

## 🔧 Required Fixes Before First Startup

### Fix #1: Update Kubernetes Context References

**Required:** Yes
**Priority:** HIGH
**Effort:** Low

```bash
# Option A: Update Tiltfiles (Recommended)
cd /Users/panda/catalyst-devspace/workspace/.scratch/talos-homelab

# Update root Tiltfile
sed -i '' 's/kubernetes-admin@talos00/admin@homelab-single/g' Tiltfile

# Update infrastructure Tiltfile
sed -i '' 's/kubernetes-admin@talos00/admin@homelab-single/g' infrastructure/Tiltfile

# Update arr-stack Tiltfile
sed -i '' 's/kubernetes-admin@talos00/admin@homelab-single/g' applications/arr-stack/Tiltfile

# Verify changes
grep "allow_k8s_contexts" Tiltfile infrastructure/Tiltfile applications/arr-stack/Tiltfile
```

### Fix #2: Verify Kustomize Overlays Exist

**Required:** Yes
**Priority:** HIGH
**Effort:** Low

```bash
# Check arr-stack overlays
ls -la applications/arr-stack/overlays/dev/

# Should see: kustomization.yaml and overlay files
```

---

## 📋 First Startup Checklist

### Pre-Startup
- [ ] Fix #1: Update context references (sed commands above)
- [ ] Fix #2: Verify `applications/arr-stack/overlays/dev/` exists
- [ ] Verify Flux is healthy: `flux get all`
- [ ] Check no port conflicts: `lsof -i :10350` (Tilt UI port)

### Startup Options

**Option 1: Minimal (Recommended for first run)**
```bash
# Start with stream mode to see all output
tilt up --stream

# This will:
# - Suspend Flux (by default)
# - Attach to existing infrastructure resources
# - Create media-dev namespace
# - Deploy arr-stack to media-dev
# - Start Tilt UI on localhost:10350
```

**Option 2: Without Flux Suspension** (Advanced)
```bash
# Keep Flux running alongside Tilt
SUSPEND_FLUX=false tilt up --stream

# Use this if:
# - You want Flux to continue managing prod
# - You're only developing in media-dev
# - You understand potential conflicts
```

**Option 3: Specific Resource** (Testing)
```bash
# Only monitor specific resources
tilt up monitoring:prometheus --stream

# Or only arr-stack
tilt up arr-stack --stream
```

### Post-Startup Verification
- [ ] Tilt UI accessible: http://localhost:10350
- [ ] No errors in Tilt output
- [ ] Flux status: `flux get kustomizations` (check if suspended)
- [ ] Media-dev namespace created: `kubectl get ns media-dev`
- [ ] Port forwards working (test one service)

### Shutdown
```bash
# Graceful shutdown (resumes Flux if suspended)
tilt down

# Force quit (if stuck)
Ctrl+C
```

---

## 🎯 Expected Behavior on First Startup

### What Tilt WILL Do:
1. ✅ Suspend Flux (if `flux_suspend=true`)
2. ✅ Attach to existing monitoring resources (Prometheus, Grafana, etc.)
3. ✅ Attach to existing observability resources (Graylog, OpenSearch, etc.)
4. ✅ Create `media-dev` namespace
5. ✅ Deploy arr-stack to `media-dev` using `overlays/dev`
6. ✅ Set up port-forwards for all configured resources
7. ✅ Start Tilt UI on `localhost:10350`
8. ✅ Watch for file changes in `infrastructure/` and `applications/`

### What Tilt WILL NOT Do:
1. ❌ Modify Flux-managed production resources
2. ❌ Deploy to `media-prod` namespace
3. ❌ Change Helm releases managed by Flux
4. ❌ Delete or recreate existing infrastructure
5. ❌ Interfere with `media-prod` workloads

---

## 🚨 Common First-Run Issues & Solutions

### Issue: "Context validation failed"
**Symptom:**
```
Error: context kubernetes-admin@talos00 is not allowed
```

**Solution:** Run Fix #1 (update context references)

---

### Issue: "Kustomization not found"
**Symptom:**
```
Error: overlays/dev: no such file or directory
```

**Solution:**
```bash
# Check if overlay exists
ls applications/arr-stack/overlays/dev/kustomization.yaml

# If missing, check alternative locations
find applications/arr-stack -name "kustomization.yaml"
```

---

### Issue: "Port already in use"
**Symptom:**
```
Error: bind :9090: address already in use
```

**Solution:**
```bash
# Find process using the port
lsof -i :9090

# Kill it or change Tilt port-forward config
```

---

### Issue: "Flux suspension failed"
**Symptom:**
```
Error: failed to suspend flux-system
```

**Solution:**
```bash
# Check Flux status
flux get kustomizations

# Resume if stuck
flux resume kustomization flux-system

# Restart Tilt without suspension
SUSPEND_FLUX=false tilt up
```

---

## 🎬 Recommended First Startup Workflow

```bash
# 1. Fix context references
cd /Users/panda/catalyst-devspace/workspace/.scratch/talos-homelab
sed -i '' 's/kubernetes-admin@talos00/admin@homelab-single/g' Tiltfile infrastructure/Tiltfile applications/arr-stack/Tiltfile

# 2. Verify Flux is healthy
flux get all

# 3. Start Tilt in stream mode (see all output)
tilt up --stream

# 4. Open Tilt UI (in another terminal or browser)
open http://localhost:10350

# 5. Monitor startup
# Watch Tilt UI for:
# - Green checkmarks on all resources
# - No red error states
# - Port forwards showing "active"

# 6. Test a port-forward
curl http://localhost:9090/-/healthy  # Prometheus health check

# 7. When done testing
tilt down
```

---

## 📊 Resource Overview

### Resources Tilt Will Attach To (Existing):
| Resource | Namespace | Type | Port Forward | Flux-Managed |
|----------|-----------|------|--------------|--------------|
| prometheus | monitoring | StatefulSet | 9090 | ✅ HelmRelease |
| grafana | monitoring | Deployment | 3000 | ✅ HelmRelease |
| alertmanager | monitoring | StatefulSet | 9093 | ✅ HelmRelease |
| graylog | observability | StatefulSet | 9000 | ✅ HelmRelease |
| opensearch | observability | StatefulSet | 9200 | ✅ HelmRelease |
| fluent-bit | observability | DaemonSet | - | ✅ HelmRelease |
| traefik | traefik | DaemonSet | 8000, 8888 | ✅ Kustomize |
| argocd-server | argocd | Deployment | 8443 | ✅ Kustomize |
| docker-registry | registry | Deployment | 5000 | ✅ Kustomize |

### Resources Tilt Will Deploy (New):
| Resource | Namespace | Type | Port Forward | Source |
|----------|-----------|------|--------------|--------|
| sonarr | media-dev | Deployment | 8989 | overlays/dev |
| radarr | media-dev | Deployment | 7878 | overlays/dev |
| prowlarr | media-dev | Deployment | 9696 | overlays/dev |
| overseerr | media-dev | Deployment | 5055 | overlays/dev |
| plex | media-dev | Deployment | 32400 | overlays/dev |
| jellyfin | media-dev | Deployment | 8096 | overlays/dev |
| tdarr | media-dev | Deployment | 8265, 8266 | overlays/dev |
| homepage | media-dev | Deployment | 3000 | overlays/dev |
| postgresql | media-dev | StatefulSet | - | overlays/dev |

---

## 🔄 Tilt + Flux Coexistence Strategy

### Production (media-prod)
- ✅ Managed by Flux
- ✅ Auto-reconciles from Git
- ✅ No Tilt interference

### Development (media-dev)
- ✅ Managed by Tilt
- ✅ Live reload from local changes
- ✅ Separate namespace = no conflicts

### Infrastructure (monitoring, observability, etc.)
- ✅ Managed by Flux
- ✅ Tilt attaches for monitoring only
- ✅ Port-forwards for local access

**Golden Rule:** Tilt monitors infrastructure, deploys to dev namespaces only

---

## 📝 Post-First-Run Actions

After successful first startup:

1. [ ] Document any issues encountered
2. [ ] Test file hot-reload (edit a ConfigMap, see if Tilt auto-applies)
3. [ ] Test manual triggers (flux-reconcile button)
4. [ ] Verify Flux resume works: `tilt down && flux get kustomizations`
5. [ ] Update this document with lessons learned

---

## 🎓 Learning Resources

**Tilt Concepts:**
- **k8s_resource:** Attach to existing Kubernetes resources
- **k8s_yaml:** Apply YAML to cluster
- **watch_file:** Hot-reload when files change
- **local_resource:** Run local commands (manual triggers)
- **port_forwards:** Automatic port forwarding

**Tilt UI Navigation:**
- Labels: Click to filter by label (monitoring, automation, etc.)
- Resources: Click to see logs and details
- Triggers: Manual buttons (force reconcile, deploy, etc.)
- Logs: Real-time streaming

---

## ✅ READY TO START

**Summary:**
- ⚠️ Fix context references (one sed command)
- ✅ Flux is healthy
- ✅ Cluster is ready
- ✅ Tilt setup is well-architected

**First Command:**
```bash
# After fixing context references
tilt up --stream
```

**Expected Result:** Tilt UI on localhost:10350 with all resources green

---

**Last Updated:** 2025-11-25
**Next Review:** After first successful startup
