# GELF Structured Logging - Initial Findings

**Date:** 2025-11-25
**Status:** Analysis Complete - Ready for Implementation

---

## Executive Summary

**Root Cause Identified:**
Fluent Bit is sending GELF messages with **ISO8601 string timestamps** instead of **numeric Unix epoch timestamps** as required by the GELF specification. This causes:

1. ✅ Graylog accepts messages but logs warnings
2. ❌ OpenSearch rejects messages with indexing errors
3. ❌ Data loss for affected log messages
4. ❌ Performance overhead from string parsing

**Impact:**
- **WARNING**: `GELF message has invalid "timestamp": 2025-11-25T19:54:57.49464557Z (type: STRING)`
- **ERROR**: `Failed to index [6] messages - mapper_parsing_exception: failed to parse field [ts] of type [date]`

**Solution:**
Update Fluent Bit configuration to send numeric Unix timestamps and add proper GELF field mapping.

---

## Current Fluent Bit Configuration Analysis

### Input Configuration

```ini
[INPUT]
    Name tail
    Path /var/log/containers/*.log
    multiline.parser docker, cri
    Tag kube.*
    Mem_Buf_Limit 5MB
    Skip_Long_Lines On
```

**Status:** ✅ Correct - Tails Kubernetes container logs

### Kubernetes Filter

```ini
[FILTER]
    Name kubernetes
    Match kube.*
    Kube_URL https://kubernetes.default.svc:443
    Kube_CA_File /var/run/secrets/kubernetes.io/serviceaccount/ca.crt
    Kube_Token_File /var/run/secrets/kubernetes.io/serviceaccount/token
    Kube_Tag_Prefix kube.var.log.containers.
    Merge_Log On
    Keep_Log Off
    K8S-Logging.Parser On
    K8S-Logging.Exclude On
```

**Status:** ✅ Good - Enriches logs with Kubernetes metadata

### Modify Filters

```ini
[FILTER]
    Name modify
    Match *
    Add cluster talos-homelab

# Ensure log field exists for GELF short_message
[FILTER]
    Name modify
    Match *
    Copy message log
    Condition Key_Does_Not_Exist log

[FILTER]
    Name modify
    Match *
    Copy stream log
    Condition Key_Does_Not_Exist log

[FILTER]
    Name modify
    Match *
    Set log no_message
    Condition Key_Does_Not_Exist log

# Ensure kubernetes_host field exists for GELF host
[FILTER]
    Name modify
    Match *
    Copy kubernetes.host kubernetes_host
    Condition Key_Does_Not_Exist kubernetes_host

[FILTER]
    Name modify
    Match *
    Set kubernetes_host talos00
    Condition Key_Does_Not_Exist kubernetes_host
```

**Status:** ⚠️ Partial - Has fallback logic but missing timestamp handling

### GELF Output

```ini
[OUTPUT]
    Name gelf
    Match *
    Host graylog-web.observability.svc.cluster.local
    Port 12201
    Mode tcp
    Gelf_Short_Message_Key log
    Gelf_Host_Key kubernetes_host
```

**Status:** ❌ **CRITICAL ISSUE** - No timestamp configuration!

**Problem:** Fluent Bit's GELF output plugin is using default timestamp handling, which sends ISO8601 strings instead of numeric epoch.

---

## Problem 1: Timestamp Format

### What's Happening

**Fluent Bit sends:**
```json
{
  "timestamp": "2025-11-25T19:54:57.49464557Z",
  "log": "message text",
  "kubernetes_host": "pod-name"
}
```

**GELF spec requires:**
```json
{
  "version": "1.1",
  "host": "pod-name",
  "short_message": "message text",
  "timestamp": 1732565697.494645,
  "level": 6
}
```

### GELF Output Plugin Behavior

The Fluent Bit GELF output plugin:
- Automatically adds `version` field (1.1)
- Maps `kubernetes_host` → `host`
- Maps `log` → `short_message`
- **BUG**: Adds `timestamp` as ISO8601 string instead of numeric

### Why OpenSearch Fails

OpenSearch index mapping expects `ts` field as:
- Type: `date`
- Format: `strict_date_optional_time||epoch_millis`

When Fluent Bit sends scientific notation (`1.764E9`) or ISO string, OpenSearch rejects it:
```
mapper_parsing_exception: failed to parse field [ts] of type [date]
Preview of field's value: '1.764099672486776E9'
```

---

## Problem 2: Missing Structured Fields

### Current State

Logs arrive with minimal structure:
- `host` = pod name
- `short_message` = raw log line
- `timestamp` = string (wrong format)
- `cluster` = talos-homelab

### Missing Critical Fields

**Kubernetes Metadata:**
- `_namespace` - Kubernetes namespace
- `_pod` - Pod name
- `_container` - Container name
- `_node` - Node name
- `_app` - Application label

**Log Metadata:**
- `_log_level` - Parsed log level (INFO, ERROR, etc.)
- `level` - Syslog severity number (0-7)
- `_source` - Log source type

**Impact:** Can't filter or dashboard by namespace, app, or log level.

---

## Problem 3: Graylog CrashLoopBackOff

### Current Status

```
NAME        READY   STATUS             RESTARTS      AGE
graylog-0   0/1     CrashLoopBackOff   4 (22s ago)   28m
```

### Observed Behavior

1. Graylog starts successfully
2. Accepts GELF messages (with timestamp warnings)
3. Tries to index to OpenSearch
4. OpenSearch rejects malformed timestamps
5. Graylog continues running for ~5-10 minutes
6. Eventually crashes (cause TBD - need more investigation)

### Theories

**Theory 1: Resource Exhaustion**
- 16GB heap might be insufficient
- Index errors queue up in memory
- Eventually OOMs

**Theory 2: Index Error Accumulation**
- Too many failed indexing operations
- Error handling code has bug
- Triggers crash

**Theory 3: Readiness Probe Failure**
- Probe configuration: `initialDelaySeconds: 30`, `periodSeconds: 10`, `failureThreshold: 3`
- If API becomes unresponsive, probe fails 3 times = restart

**Next Steps for Graylog:**
1. Fix timestamp format (will reduce index errors dramatically)
2. Monitor after fix to see if crashes continue
3. If still crashing, investigate:
   - Check for memory issues (`kubectl top pod graylog-0`)
   - Review readiness probe (may need adjustment)
   - Check OpenSearch connectivity/health

---

## Solution: Updated Fluent Bit Configuration

### Key Changes

1. **Timestamp Conversion**: Use `record_modifier` filter to convert timestamp to numeric epoch
2. **Field Extraction**: Add Kubernetes metadata as GELF custom fields
3. **Log Level Parsing**: Extract and map log levels to syslog severity
4. **GELF Compliance**: Ensure all fields match GELF 1.1 specification

### Proposed Configuration

```ini
[SERVICE]
    Daemon Off
    Flush 1
    Log_Level info
    Parsers_File parsers.conf
    Parsers_File custom_parsers.conf
    HTTP_Server On
    HTTP_Listen 0.0.0.0
    HTTP_Port 2020
    Health_Check On

[INPUT]
    Name tail
    Path /var/log/containers/*.log
    multiline.parser docker, cri
    Tag kube.*
    Mem_Buf_Limit 5MB
    Skip_Long_Lines On

[FILTER]
    Name kubernetes
    Match kube.*
    Kube_URL https://kubernetes.default.svc:443
    Kube_CA_File /var/run/secrets/kubernetes.io/serviceaccount/ca.crt
    Kube_Token_File /var/run/secrets/kubernetes.io/serviceaccount/token
    Kube_Tag_Prefix kube.var.log.containers.
    Merge_Log On
    Keep_Log Off
    K8S-Logging.Parser On
    K8S-Logging.Exclude On

# Add cluster identifier
[FILTER]
    Name record_modifier
    Match *
    Record _cluster talos-homelab

# Add Kubernetes metadata as GELF custom fields
[FILTER]
    Name record_modifier
    Match *
    Record _namespace ${kubernetes['namespace_name']}
    Record _pod ${kubernetes['pod_name']}
    Record _container ${kubernetes['container_name']}
    Record _node ${kubernetes['host']}

# Add app label if exists
[FILTER]
    Name modify
    Match *
    Copy kubernetes.labels.app _app
    Condition Key_Exists kubernetes.labels.app

# Ensure log field exists (for GELF short_message)
[FILTER]
    Name modify
    Match *
    Copy message log
    Condition Key_Does_Not_Exist log

[FILTER]
    Name modify
    Match *
    Copy stream log
    Condition Key_Does_Not_Exist log

[FILTER]
    Name modify
    Match *
    Set log no_message
    Condition Key_Does_Not_Exist log

# Set host field for GELF (use pod name)
[FILTER]
    Name modify
    Match *
    Copy kubernetes.pod_name host
    Condition Key_Does_Not_Exist host

[FILTER]
    Name modify
    Match *
    Set host talos00
    Condition Key_Does_Not_Exist host

# Parse log level from message and map to syslog severity
[FILTER]
    Name lua
    Match *
    script /fluent-bit/scripts/gelf-enrich.lua
    call enrich_gelf

[OUTPUT]
    Name gelf
    Match *
    Host graylog-web.observability.svc.cluster.local
    Port 12201
    Mode tcp
    Gelf_Short_Message_Key log
    Gelf_Host_Key host
    # CRITICAL: Do NOT set Gelf_Timestamp_Key - let plugin handle it correctly
    # The plugin will use Fluent Bit's internal timestamp (numeric epoch)
```

### Lua Script for Log Level Parsing

**File:** `/fluent-bit/scripts/gelf-enrich.lua`

```lua
function enrich_gelf(tag, timestamp, record)
    -- Extract log level from message
    local message = record["log"] or ""

    -- Map log levels to syslog severity
    local level_map = {
        ["FATAL"] = 2,    -- Critical
        ["PANIC"] = 2,    -- Critical
        ["ERROR"] = 3,    -- Error
        ["WARN"] = 4,     -- Warning
        ["WARNING"] = 4,  -- Warning
        ["INFO"] = 6,     -- Informational
        ["DEBUG"] = 7,    -- Debug
        ["TRACE"] = 7     -- Debug
    }

    -- Default to informational
    record["level"] = 6
    record["_log_level"] = "INFO"

    -- Search for log level in message
    for level_name, level_num in pairs(level_map) do
        -- Case-insensitive pattern matching
        if string.match(message:upper(), level_name) then
            record["level"] = level_num
            record["_log_level"] = level_name
            break
        end
    end

    -- Extract app from Kubernetes labels if not already set
    if record["kubernetes"] and record["kubernetes"]["labels"] then
        if record["kubernetes"]["labels"]["app"] then
            record["_app"] = record["kubernetes"]["labels"]["app"]
        elseif record["kubernetes"]["labels"]["app.kubernetes.io/name"] then
            record["_app"] = record["kubernetes"]["labels"]["app.kubernetes.io/name"]
        end
    end

    return 2, timestamp, record
end
```

---

## Expected Message Format After Fix

### Before (Current - Broken)

```json
{
  "timestamp": "2025-11-25T19:54:57.49464557Z",
  "log": "INFO: Application started",
  "kubernetes_host": "my-pod-xyz",
  "cluster": "talos-homelab"
}
```

### After (Fixed - GELF Compliant)

```json
{
  "version": "1.1",
  "host": "my-pod-xyz",
  "short_message": "INFO: Application started",
  "timestamp": 1732565697.494645,
  "level": 6,
  "_log_level": "INFO",
  "_namespace": "observability",
  "_pod": "my-pod-xyz",
  "_container": "app",
  "_node": "talos00",
  "_app": "graylog",
  "_cluster": "talos-homelab"
}
```

---

## Implementation Plan

### Step 1: Create Lua Script

Create ConfigMap with Lua script:

```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: fluent-bit-scripts
  namespace: observability
data:
  gelf-enrich.lua: |
    [Lua script content from above]
```

### Step 2: Update Fluent Bit HelmRelease

Modify `infrastructure/base/observability/fluent-bit/helmrelease.yaml`:

```yaml
spec:
  values:
    config:
      service: |
        [SERVICE]
            Daemon Off
            Flush 1
            Log_Level info
            Parsers_File parsers.conf
            Parsers_File custom_parsers.conf
            HTTP_Server On
            HTTP_Listen 0.0.0.0
            HTTP_Port 2020
            Health_Check On

      inputs: |
        [INPUT]
            Name tail
            Path /var/log/containers/*.log
            multiline.parser docker, cri
            Tag kube.*
            Mem_Buf_Limit 5MB
            Skip_Long_Lines On

      filters: |
        [Proposed filter configuration from above]

      outputs: |
        [Proposed output configuration from above]

    # Mount Lua script
    luaScripts:
      gelf-enrich.lua: |
        [Lua script content]
```

### Step 3: Deploy and Test

```bash
# Apply configuration
kubectl apply -f infrastructure/base/observability/fluent-bit/

# Force Flux reconciliation
flux reconcile helmrelease fluent-bit -n observability

# Wait for rollout
kubectl rollout status daemonset fluent-bit -n observability

# Check logs for errors
kubectl logs -n observability -l app.kubernetes.io/name=fluent-bit --tail=50

# Verify Graylog stops showing timestamp warnings
kubectl logs -n observability graylog-0 --tail=50 | grep -i "invalid.*timestamp"

# Should see: No matches (warnings gone!)
```

### Step 4: Verify in Graylog UI

1. Access Graylog: `http://graylog.talos00`
2. Login: `admin / adminadminadmin16`
3. Search for recent messages
4. Check fields:
   - `timestamp` should be numeric
   - `_namespace`, `_pod`, `_container` should exist
   - `level` should be 0-7
   - `_log_level` should be text (INFO, ERROR, etc.)

---

## Testing Checklist

- [ ] Lua script created and mounted
- [ ] Fluent Bit configuration updated
- [ ] Flux reconciliation successful
- [ ] Fluent Bit pods restarted
- [ ] No connection errors in Fluent Bit logs
- [ ] No timestamp warnings in Graylog logs
- [ ] No indexing errors in Graylog logs
- [ ] Messages visible in Graylog UI
- [ ] All custom fields present (_namespace, _pod, etc.)
- [ ] Timestamp field is numeric
- [ ] Log levels parsed correctly
- [ ] Graylog remains stable (no crashes)

---

## Next Steps After Fix

1. **Monitor Graylog Stability**
   - Check if crashes stop after timestamp fix
   - If still crashing, investigate resource limits

2. **Create Dashboards**
   - Infrastructure Overview
   - Traefik Access Logs
   - Application-specific dashboards

3. **Add Application-Specific Parsers**
   - Traefik access log parsing
   - ArgoCD sync event parsing
   - Arr-stack event parsing

4. **Set Up Alerting**
   - Alert on ERROR/CRITICAL level logs
   - Alert on high error rate
   - Alert on specific error patterns

---

## References

- Fluent Bit GELF Output: https://docs.fluentbit.io/manual/pipeline/outputs/gelf
- GELF Specification: https://go2docs.graylog.org/current/getting_in_log_data/gelf.html
- Fluent Bit Record Modifier: https://docs.fluentbit.io/manual/pipeline/filters/record-modifier
- Fluent Bit Lua Filter: https://docs.fluentbit.io/manual/pipeline/filters/lua
