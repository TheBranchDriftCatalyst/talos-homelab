# Catalyst DNS Sync - Quick Start

## 5-Minute Setup

### Step 1: One-time Development Setup
```bash
task dev:setup
```

This installs Air and initializes the Go module.

### Step 2: Start Dev Mode
```bash
task dev
```

Your `/etc/hosts` will now auto-update when you create/delete Ingress resources!

---

## What Just Happened?

1. Air started watching your code for changes
2. The controller is watching your Kubernetes cluster
3. When it finds IngressRoute resources matching `*.talos00`:
   - Extracts the hostnames
   - Updates `/etc/hosts` with a managed block
4. You can now access services like `http://grafana.talos00`

---

## Test It

### Create a test Ingress
```bash
kubectl apply -f - <<EOF
apiVersion: traefik.io/v1alpha1
kind: IngressRoute
metadata:
  name: test-app
  namespace: default
spec:
  routes:
  - match: Host(\`test.talos00\`)
    services:
    - name: whoami
      port: 80
EOF
```

### Check your /etc/hosts
```bash
grep "test.talos00" /etc/hosts
# Should show: 192.168.1.54  test.talos00
```

### Delete the Ingress
```bash
kubectl delete ingressroute test-app
```

### Verify cleanup
```bash
grep "test.talos00" /etc/hosts
# Should be gone!
```

---

## Check Metrics

```bash
curl http://localhost:8080/metrics | grep catalyst_dns_sync
```

---

## Production Deployment

When ready to deploy to cluster:

```bash
# 1. Create API token secret
kubectl create secret generic technitium-api-token \
  --from-literal=token=YOUR_TOKEN \
  -n infrastructure

# 2. Deploy
make deploy

# 3. Check logs
kubectl logs -n infrastructure -l app=catalyst-dns-sync -f
```

---

## Troubleshooting

**Air not found?**
```bash
task install-air
```

**Sudo password prompt?**
```bash
# Required for /etc/hosts updates in dev mode
# Run: sudo -v
```

**Port already in use?**
```bash
# Check what's using port 8080/8081
lsof -i :8080
lsof -i :8081
```

---

## Next Steps

1. Read the full [README.md](./README.md)
2. Check [MVP Definition](../docs/proposals/CATALYST-DNS-SYNC-MVP.md)
3. Review [Technical Proposal](../docs/proposals/CATALYST-DNS-SYNC-PROPOSAL.md)
4. Start implementing! See checklist in MVP doc

---

**Happy coding!** 🚀
