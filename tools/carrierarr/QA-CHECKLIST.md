# QA Checklist: Worker Self-Registration via RabbitMQ

Manual testing checklist for the RabbitMQ-based worker registration system.

## Prerequisites

- [ ] Kubernetes cluster accessible (`kubectl get nodes` works)
- [ ] RabbitMQ pod running (`kubectl get pods -n catalyst-llm | grep rabbitmq`)
- [ ] AWS credentials configured for EC2 access

## UI Access Points

| Service | URL | Purpose |
|---------|-----|---------|
| llm-proxy UI | http://llm.talos00/_/ui | Main control panel |
| RabbitMQ Console | http://rabbitmq.talos00 | Queue monitoring |
| Control-plane API | http://control-plane.ec2-agents.svc:8090 | Fleet API (internal) |

---

## Phase 1: Infrastructure Verification

### 1.1 RabbitMQ Agents Vhost
- [ ] Login to RabbitMQ console: http://rabbitmq.talos00 (admin/admin or check secret)
- [ ] Navigate to "Admin" → "Virtual Hosts"
- [ ] Verify `agents` vhost exists
- [ ] Navigate to "Exchanges" (select `agents` vhost)
- [ ] Verify exchanges exist:
  - [ ] `agents.registration` (direct)
  - [ ] `agents.heartbeat` (fanout)
  - [ ] `agents.commands` (topic)
- [ ] Navigate to "Queues" (select `agents` vhost)
- [ ] Verify queues exist:
  - [ ] `registration.control-plane`
  - [ ] `heartbeat.control-plane`

### 1.2 ec2-agents Namespace
```bash
# Run these commands and verify output
kubectl get ns ec2-agents
kubectl get pods -n ec2-agents
kubectl get svc -n ec2-agents
kubectl get ingressroute -n ec2-agents
```

- [ ] Namespace exists
- [ ] control-plane pod is Running
- [ ] Services created (grpc:50051, http:8090)
- [ ] IngressRoute configured

### 1.3 Control-Plane Health
```bash
# Port-forward to test locally
kubectl port-forward -n ec2-agents svc/control-plane 8090:8090 &

# Test endpoints
curl http://localhost:8090/health
curl http://localhost:8090/version
curl http://localhost:8090/api/v1/fleet
curl http://localhost:8090/api/v1/nodes
curl http://localhost:8090/api/v1/stats
```

- [ ] `/health` returns `ok`
- [ ] `/version` returns JSON with version
- [ ] `/api/v1/fleet` returns JSON (nodes array may be empty)
- [ ] `/api/v1/nodes` returns empty array or node list
- [ ] `/api/v1/stats` returns statistics

---

## Phase 2: Worker Registration Flow

### 2.1 Build and Push Worker-Agent
```bash
cd tools/ec2-agent
make build
# Push to registry if needed
```

- [ ] Binary builds successfully
- [ ] Binary includes RabbitMQ support (`./bin/linux-amd64/worker-agent --help | grep rabbitmq`)

### 2.2 Build GPU Worker AMI
```bash
cd tools/ec2-agent/ami
packer init .
packer validate .
packer build -only="gpu-worker.*" .
```

- [ ] Packer init succeeds
- [ ] Packer validate succeeds
- [ ] AMI builds successfully
- [ ] Note AMI ID: `ami-_______________`

### 2.3 Launch Test Worker
```bash
# Update LLM_INSTANCE_TYPE as needed
LLM_INSTANCE_TYPE=g6.xlarge ./scripts/hybrid-llm/llm-worker.sh start
```

- [ ] Instance launches
- [ ] Note Instance ID: `i-_______________`

### 2.4 Verify Worker Registration (within 2 minutes)

**RabbitMQ Console:**
- [ ] Navigate to Queues → `registration.control-plane`
- [ ] Check "Message rates" - should show incoming messages
- [ ] Navigate to Queues → `heartbeat.control-plane`
- [ ] Check heartbeats arriving every 30s

**Control-Plane API:**
```bash
curl http://localhost:8090/api/v1/nodes
curl http://localhost:8090/api/v1/nodes?type=gpu-worker
curl http://localhost:8090/api/v1/fleet
```

- [ ] Node appears in `/api/v1/nodes` list
- [ ] Node has correct `nebula_ip`
- [ ] Node shows `connected: true`
- [ ] Node `health_status: "healthy"`

**llm-proxy UI:**
- [ ] Open http://llm.talos00/_/ui
- [ ] Check Control Panel shows fleet info
- [ ] `/_/fleet` endpoint shows worker

---

## Phase 3: Heartbeat & TTL Verification

### 3.1 Healthy Heartbeats
```bash
# Watch node status over time
watch -n 5 'curl -s http://localhost:8090/api/v1/nodes | jq .'
```

- [ ] `last_seen` updates every ~30 seconds
- [ ] `health_status` stays "healthy"
- [ ] `uptime_seconds` increases

### 3.2 Stale Detection (optional - requires stopping worker-agent)
```bash
# SSH to worker and stop agent (or terminate instance)
# Wait 2+ minutes
curl http://localhost:8090/api/v1/nodes | jq '.[] | select(.health_status == "stale")'
```

- [ ] After 2 min without heartbeat: `health_status: "stale"`
- [ ] After 5 min without heartbeat: node removed or marked dead

---

## Phase 4: llm-proxy Integration

### 4.1 Fleet API Integration
```bash
# Check llm-proxy logs
kubectl logs -n catalyst-llm deployment/llm-proxy | grep -i fleet
```

- [ ] Logs show "Fleet API: http://control-plane.ec2-agents..."
- [ ] No connection errors

### 4.2 Dynamic Remote URL
```bash
curl http://llm.talos00/_/fleet
curl http://llm.talos00/_/status
```

- [ ] `/_/fleet` shows `enabled: true`
- [ ] `/_/fleet` shows `gpu_workers` count > 0
- [ ] `/_/fleet` shows `best_worker` with `nebula_ip` and `ollama_url`
- [ ] `/_/status` shows correct remote target

### 4.3 Request Routing
```bash
# Make a test request through proxy
curl http://llm.talos00/api/tags
```

- [ ] Request succeeds (returns Ollama tags)
- [ ] Check which backend was used (local vs remote)

---

## Phase 5: Command Execution

### 5.1 Send Command via API
```bash
# Get node ID first
NODE_ID=$(curl -s http://localhost:8090/api/v1/nodes | jq -r '.[0].id')

# Send a status command (safe)
curl -X POST http://localhost:8090/api/v1/command \
  -H "Content-Type: application/json" \
  -d "{\"node_id\": \"$NODE_ID\", \"command\": \"status\"}"
```

- [ ] Command accepted (check response)
- [ ] Check control-plane logs for command routing

### 5.2 Shutdown Command (DESTRUCTIVE - use with caution)
```bash
# Only if you want to terminate the worker!
curl -X POST http://localhost:8090/api/v1/command \
  -H "Content-Type: application/json" \
  -d "{\"node_id\": \"$NODE_ID\", \"command\": \"shutdown\", \"args\": {\"reason\": \"QA test\"}}"
```

- [ ] Command sent successfully
- [ ] Worker shuts down
- [ ] Node removed from fleet after timeout

---

## Phase 6: Error Handling & Recovery

### 6.1 RabbitMQ Connection Loss
```bash
# Scale down RabbitMQ temporarily
kubectl scale statefulset rabbitmq -n catalyst-llm --replicas=0
# Wait 30s, then scale back up
kubectl scale statefulset rabbitmq -n catalyst-llm --replicas=1
```

- [ ] Control-plane logs show reconnection attempts
- [ ] Worker-agent logs show reconnection attempts
- [ ] Both reconnect successfully after RabbitMQ is back

### 6.2 Control-Plane Restart
```bash
kubectl rollout restart deployment/control-plane -n ec2-agents
```

- [ ] Workers re-register after control-plane restart
- [ ] Fleet state recovers

### 6.3 Worker-Agent Crash Recovery
```bash
# SSH to worker
sudo systemctl restart worker-agent
```

- [ ] Agent reconnects to RabbitMQ
- [ ] Heartbeats resume
- [ ] Node status returns to healthy

---

## Cleanup

```bash
# Terminate test worker
./scripts/hybrid-llm/llm-worker.sh stop

# Verify cleanup
curl http://localhost:8090/api/v1/nodes  # Should be empty or node removed
```

- [ ] Worker terminated
- [ ] Node removed from fleet (after TTL)

---

## Log Locations

| Component | Location |
|-----------|----------|
| Control-plane | `kubectl logs -n ec2-agents deployment/control-plane` |
| llm-proxy | `kubectl logs -n catalyst-llm deployment/llm-proxy` |
| Worker-agent (EC2) | `/var/log/userdata.log`, `journalctl -u worker-agent` |
| RabbitMQ | `kubectl logs -n catalyst-llm statefulset/rabbitmq` |

---

## Common Issues

| Issue | Check |
|-------|-------|
| Worker not registering | Check worker-agent logs, verify RABBITMQ_URL in /etc/worker-agent/env |
| Control-plane not seeing workers | Check RabbitMQ queues have messages, verify consumer is subscribed |
| llm-proxy shows fleet disabled | Verify FLEET_API_URL env var, check control-plane service DNS |
| Stale detection not working | Verify heartbeat queue receiving messages, check TTL thresholds |

---

## Test Results

| Phase | Status | Notes |
|-------|--------|-------|
| 1. Infrastructure | ⬜ | |
| 2. Registration | ⬜ | |
| 3. Heartbeat/TTL | ⬜ | |
| 4. llm-proxy | ⬜ | |
| 5. Commands | ⬜ | |
| 6. Recovery | ⬜ | |

**Tested By:** _______________
**Date:** _______________
**AMI Version:** _______________
