# Gitleaks Remediation Report

**Generated**: 2026-03-02
**Total Leaks Found**: 151
**Unique Commits**: 15
**Unique Files**: 5

---

## Summary by File

| File | Status | Leak Count | Secret Types |
|------|--------|------------|--------------|
| `configs/cilium-manifest.yaml` | **ACTIVE** | 120 | private-key, sealed-secrets-key, ssh-private-key, ssl-certificate-private-key |
| `infrastructure/base/cilium/clustermesh/clustermesh-apiserver.yaml` | **ACTIVE** | 16 | private-key, sealed-secrets-key, ssh-private-key, ssl-certificate-private-key |
| `applications/gaming/base/pterodactyl/kuber/config.yaml` | HISTORICAL | 10 | generic-api-key, high-entropy-base64, jwt, kubernetes-service-account-token |
| `infrastructure/base/nebula-mesh/secret.yaml` | HISTORICAL | 1 | private-key |
| `applications/zipline/deployment.yaml` | **ACTIVE** | 1 | postgresql-password |

### Status Legend
- **ACTIVE**: File still exists in current working tree - needs current fix + history cleanup
- **HISTORICAL**: File deleted from tree - only needs history cleanup (safe to scrub)

---

## Remediation Options

### Option 1: git-filter-repo (Recommended for complete removal)
Completely removes secrets from history. **Requires force push.**

```bash
# Install if needed
brew install git-filter-repo

# Remove specific files from all history
git filter-repo --path configs/cilium-manifest.yaml --invert-paths
```

### Option 2: BFG Repo-Cleaner (Faster for large repos)
```bash
# Install
brew install bfg

# Remove files containing secrets
bfg --delete-files cilium-manifest.yaml
git reflog expire --expire=now --all && git gc --prune=now --aggressive
```

### Option 3: Add to .gitleaks.toml allowlist (If secrets are not real/rotated)
```toml
[allowlist]
paths = [
  '''configs/cilium-manifest\.yaml''',
]
```

---

## Detailed Findings by File

### 1. configs/cilium-manifest.yaml
**Status**: ACTIVE - file exists in current tree
**Recommendation**: Remove from history, add to .gitignore
**Action**: Fix current file THEN scrub history

| Commit | Date | Message | Lines |
|--------|------|---------|-------|
| `e5eda33f` | 2025-12-16 | chore: cleanup scripts and update configs | 46, 58, 70 |
| `b53d8c57` | 2025-12-06 | feat: Enable Cilium Prometheus metrics via Helm values | 46, 58, 70 |
| `45652b7e` | 2025-12-17 | chore(cilium): roll back mTLS config after connectivity failure | 46, 58, 70 |
| `6ed7ba3d` | 2025-12-17 | chore(cilium): document WireGuard+VXLAN incompatibility | 46, 58, 70 |
| `a2ed85f0` | 2025-12-17 | feat(cilium): enable SPIRE-based mTLS service mesh | 66, 78, 90 |
| `ad4d143b` | 2025-12-17 | fix(cilium): enable all Cilium dashboards in Grafana | 66, 78, 90 |
| `859dce8e` | 2025-12-17 | chore(vpn): checkpoint before dedicated NIC setup | 66, 78, 90 |
| `0c6311e2` | 2025-12-18 | feat(vpn-gateway): add gluetun pod-based VPN gateway | 66, 78, 90 |
| `9e375320` | 2026-01-13 | chore: checkpoint before carrierarr/nebula work | 73, 85, 97, 109, 121, 133, 145 |

**Secret Types**: Cilium CA certificates and private keys (for mTLS/ClusterMesh)

---

### 2. infrastructure/base/cilium/clustermesh/clustermesh-apiserver.yaml
**Status**: ACTIVE - file exists in current tree
**Recommendation**: Remove secrets from file, use External Secrets or SealedSecrets
**Action**: Fix current file THEN scrub history

| Commit | Date | Message | Lines |
|--------|------|---------|-------|
| `1ce1cec7` | 2026-01-05 | feat(cilium): add ClusterMesh infrastructure | 18, 30, 42, 54 |

**Secret Types**: ClusterMesh CA/server certificates and private keys

---

### 3. applications/gaming/base/pterodactyl/kuber/config.yaml
**Status**: HISTORICAL - file deleted from tree (safe to scrub)
**Recommendation**: Remove from git history completely
**Action**: Scrub from history only

| Commit | Date | Message | Lines |
|--------|------|---------|-------|
| `5f56bdea` | 2026-01-27 | fix(pterodactyl): update Kuber config for external access | 12, 13 |
| `9245ba8b` | 2026-01-27 | fix(pterodactyl): add Panel RBAC and fix Kuber config volume | 12, 13, 27 |
| `fd2361fc` | 2026-01-27 | fix(pterodactyl): update Kuber tokens for new cluster | 12, 13 |

**Secret Types**:
- generic-api-key (Line 12)
- high-entropy-base64 / JWT / kubernetes-service-account-token (Line 13, 27)

---

### 4. infrastructure/base/nebula-mesh/secret.yaml
**Status**: HISTORICAL - file deleted from tree (safe to scrub)
**Recommendation**: Remove from git history completely
**Action**: Scrub from history only

| Commit | Date | Message | Lines |
|--------|------|---------|-------|
| `ac0957f7` | 2026-01-05 | feat(networking): replace Liqo with Nebula mesh | 10 |

**Secret Types**: Nebula node private key

---

### 5. applications/zipline/deployment.yaml
**Status**: ACTIVE - file exists in current tree
**Recommendation**: Move password to K8s Secret or External Secret
**Action**: Fix current file THEN scrub history

| Commit | Date | Message | Lines |
|--------|------|---------|-------|
| `e51f2678` | 2026-03-01 | feat: add zipline image sharing + lan-only middleware | 62 |

**Secret Types**: postgresql-password (placeholder value "zipline")

---

## Remediation Progress

| File | Status | History Cleaned | Current Fixed |
|------|--------|-----------------|---------------|
| `applications/gaming/base/pterodactyl/kuber/config.yaml` | HISTORICAL | [ ] | N/A |
| `infrastructure/base/nebula-mesh/secret.yaml` | HISTORICAL | [ ] | N/A |
| `configs/cilium-manifest.yaml` | ACTIVE | [ ] | [ ] |
| `infrastructure/base/cilium/clustermesh/clustermesh-apiserver.yaml` | ACTIVE | [ ] | [ ] |
| `applications/zipline/deployment.yaml` | ACTIVE | [ ] | [ ] |

---

## Recommended Remediation Steps

### Step 1: Rotate All Compromised Secrets
Before removing from git history, rotate these credentials:
- [ ] Cilium CA certificates and keys
- [ ] ClusterMesh TLS certificates
- [ ] Pterodactyl/Kuber API tokens
- [ ] Nebula mesh private keys

### Step 2: Remove Files from Git History
```bash
# Backup first!
git clone --mirror . ../talos-homelab-backup.git

# Use git-filter-repo to remove sensitive files
git filter-repo \
  --path configs/cilium-manifest.yaml \
  --path infrastructure/base/cilium/clustermesh/clustermesh-apiserver.yaml \
  --path applications/gaming/base/pterodactyl/kuber/config.yaml \
  --path infrastructure/base/nebula-mesh/secret.yaml \
  --invert-paths
```

### Step 3: Update .gitignore
```gitignore
# Sensitive configs
configs/cilium-manifest.yaml
configs/*.yaml
**/secret.yaml
**/secrets.yaml
```

### Step 4: Force Push
```bash
git push --force --all
git push --force --tags
```

### Step 5: Notify Collaborators
All clones need to be re-cloned or rebased.

---

## Files to Fix in Current Working Tree

These files still exist and need secrets removed:

1. **configs/cilium-manifest.yaml** - Move to .gitignore or External Secrets
2. **applications/zipline/deployment.yaml** - Use k8s Secret instead of inline password

---

## Alternative: Add Gitleaks Allowlist

If secrets are already rotated and you just want to suppress warnings:

Create/update `.gitleaks.toml`:
```toml
[allowlist]
description = "Historical secrets that have been rotated"

[[allowlist.commits]]
id = "e5eda33f8120224465309298b0ba29e09448a80e"
[[allowlist.commits]]
id = "b53d8c57d43c88a01c14ff53fe9ec877b9d1dda9"
# ... add all commits

# Or allowlist by path pattern
[[allowlist.paths]]
path = '''configs/cilium-manifest\.yaml'''
[[allowlist.paths]]
path = '''.*secret\.yaml'''
```
