#!/usr/bin/env python3
"""Kubernetes resource cleanup script with Mimir metrics."""

import json
import os
import struct
import subprocess
import time
from datetime import datetime, timezone
from urllib.request import urlopen, Request
from urllib.error import URLError

# Config from environment
DRY_RUN = os.environ.get("DRY_RUN", "false").lower() == "true"
EXCLUDED_NAMESPACES = set(os.environ.get("EXCLUDED_NAMESPACES", "kube-system,kube-public,kube-node-lease").split(","))
MIMIR_URL = os.environ.get("MIMIR_URL", "http://mimir-nginx.monitoring.svc:80/api/v1/push")

# Thresholds in seconds
FAILED_POD_AGE = int(os.environ.get("FAILED_POD_AGE_THRESHOLD", "3600"))
EVICTED_POD_AGE = int(os.environ.get("EVICTED_POD_AGE_THRESHOLD", "1800"))
IMAGEPULL_AGE = int(os.environ.get("IMAGEPULL_AGE_THRESHOLD", "7200"))
CRASHLOOP_AGE = int(os.environ.get("CRASHLOOP_AGE_THRESHOLD", "14400"))
CRASHLOOP_RESTARTS = int(os.environ.get("CRASHLOOP_RESTART_THRESHOLD", "10"))
COMPLETED_JOB_AGE = int(os.environ.get("COMPLETED_JOB_AGE_THRESHOLD", "86400"))
ORPHAN_RS_AGE = int(os.environ.get("ORPHAN_RS_AGE_THRESHOLD", "86400"))

# Feature flags
CLEANUP_SUCCEEDED = os.environ.get("CLEANUP_SUCCEEDED_PODS", "true").lower() == "true"
CLEANUP_FAILED = os.environ.get("CLEANUP_FAILED_PODS", "true").lower() == "true"
CLEANUP_EVICTED = os.environ.get("CLEANUP_EVICTED_PODS", "true").lower() == "true"
CLEANUP_IMAGEPULL = os.environ.get("CLEANUP_IMAGEPULL_PODS", "true").lower() == "true"
CLEANUP_CRASHLOOP = os.environ.get("CLEANUP_CRASHLOOP_PODS", "false").lower() == "true"
CLEANUP_JOBS = os.environ.get("CLEANUP_COMPLETED_JOBS", "true").lower() == "true"
CLEANUP_RS = os.environ.get("CLEANUP_ORPHAN_REPLICASETS", "true").lower() == "true"
CLEANUP_CILIUM_IDS = os.environ.get("CLEANUP_CILIUM_IDENTITIES", "true").lower() == "true"


def kubectl(*args):
    """Run kubectl command and return output."""
    result = subprocess.run(["kubectl"] + list(args), capture_output=True, text=True)
    return result.stdout, result.returncode == 0


def kubectl_json(*args):
    """Run kubectl command and parse JSON output."""
    out, ok = kubectl(*args)
    if ok and out.strip():
        return json.loads(out)
    return {"items": []}


def parse_time(ts):
    """Parse ISO timestamp to epoch seconds."""
    if not ts:
        return 0
    try:
        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        return dt.timestamp()
    except Exception:
        return 0


def age_seconds(ts):
    """Get age in seconds from timestamp."""
    return time.time() - parse_time(ts)


def delete_resource(kind, namespace, name, category=None):
    """Delete a resource, returns True if deleted.

    Emits a structured JSON event line on success (or dry-run) for the
    Grafana/Loki deletion-detail table. `category` distinguishes the *reason*
    a Pod was deleted (succeeded/failed/evicted/imagepull/crashloop) since
    all of those share kind=pod. Defaults to the lowercased kind.
    """
    if namespace in EXCLUDED_NAMESPACES:
        return False

    if DRY_RUN:
        print(f"[DRY-RUN] Would delete {kind} {namespace}/{name}")
        _emit_delete_event(kind, namespace, name, category, dry_run=True)
        return True

    _, ok = kubectl("delete", kind, "-n", namespace, name, "--ignore-not-found", "--wait=false")
    if ok:
        print(f"[DELETE] {kind} {namespace}/{name}")
        _emit_delete_event(kind, namespace, name, category, dry_run=False)
    return ok


def _emit_delete_event(kind, namespace, name, category, dry_run):
    """Emit one JSON-only line per deletion for the Grafana/Loki table.
    Query: `{app_kubernetes_io_name="pod-cleanup"} | json | event="resource_delete"`.
    """
    print(json.dumps({
        "event": "resource_delete",
        "category": category or kind.lower(),
        "kind": kind,
        "namespace": namespace,
        "name": name,
        "dry_run": dry_run,
    }))


def cleanup_succeeded_pods():
    """Clean up succeeded pods."""
    if not CLEANUP_SUCCEEDED:
        return 0
    print("[INFO] Cleaning Succeeded Pods...")
    data = kubectl_json("get", "pods", "-A", "--field-selector=status.phase==Succeeded", "-o", "json")
    count = sum(1 for p in data.get("items", []) if delete_resource("pod", p["metadata"]["namespace"], p["metadata"]["name"], category="succeeded_pod"))
    print(f"[INFO] Succeeded pods: {count}")
    return count


def cleanup_failed_pods():
    """Clean up failed pods older than threshold."""
    if not CLEANUP_FAILED:
        return 0
    print(f"[INFO] Cleaning Failed Pods (>{FAILED_POD_AGE}s)...")
    data = kubectl_json("get", "pods", "-A", "--field-selector=status.phase==Failed", "-o", "json")
    count = 0
    for p in data.get("items", []):
        if age_seconds(p.get("status", {}).get("startTime")) > FAILED_POD_AGE:
            if delete_resource("pod", p["metadata"]["namespace"], p["metadata"]["name"], category="failed_pod"):
                count += 1
    print(f"[INFO] Failed pods: {count}")
    return count


def cleanup_evicted_pods():
    """Clean up evicted pods."""
    if not CLEANUP_EVICTED:
        return 0
    print("[INFO] Cleaning Evicted Pods...")
    data = kubectl_json("get", "pods", "-A", "-o", "json")
    count = 0
    for p in data.get("items", []):
        status = p.get("status", {})
        if status.get("reason") == "Evicted" and age_seconds(status.get("startTime")) > EVICTED_POD_AGE:
            if delete_resource("pod", p["metadata"]["namespace"], p["metadata"]["name"], category="evicted_pod"):
                count += 1
    print(f"[INFO] Evicted pods: {count}")
    return count


def cleanup_imagepull_pods():
    """Clean up ImagePullBackOff pods."""
    if not CLEANUP_IMAGEPULL:
        return 0
    print("[INFO] Cleaning ImagePullBackOff Pods...")
    data = kubectl_json("get", "pods", "-A", "-o", "json")
    count = 0
    for p in data.get("items", []):
        for cs in p.get("status", {}).get("containerStatuses", []):
            waiting = cs.get("state", {}).get("waiting", {})
            if waiting.get("reason") in ("ImagePullBackOff", "ErrImagePull"):
                if age_seconds(p["metadata"].get("creationTimestamp")) > IMAGEPULL_AGE:
                    if delete_resource("pod", p["metadata"]["namespace"], p["metadata"]["name"], category="imagepull_pod"):
                        count += 1
                    break
    print(f"[INFO] ImagePullBackOff pods: {count}")
    return count


def cleanup_crashloop_pods():
    """Clean up CrashLoopBackOff pods."""
    if not CLEANUP_CRASHLOOP:
        return 0
    print("[INFO] Cleaning CrashLoopBackOff Pods...")
    data = kubectl_json("get", "pods", "-A", "-o", "json")
    count = 0
    for p in data.get("items", []):
        for cs in p.get("status", {}).get("containerStatuses", []):
            waiting = cs.get("state", {}).get("waiting", {})
            if waiting.get("reason") == "CrashLoopBackOff":
                if cs.get("restartCount", 0) > CRASHLOOP_RESTARTS:
                    if age_seconds(p["metadata"].get("creationTimestamp")) > CRASHLOOP_AGE:
                        if delete_resource("pod", p["metadata"]["namespace"], p["metadata"]["name"], category="crashloop_pod"):
                            count += 1
                        break
    print(f"[INFO] CrashLoopBackOff pods: {count}")
    return count


def cleanup_completed_jobs():
    """Clean up completed jobs not owned by CronJobs."""
    if not CLEANUP_JOBS:
        return 0
    print("[INFO] Cleaning Completed Jobs...")
    data = kubectl_json("get", "jobs", "-A", "-o", "json")
    count = 0
    for j in data.get("items", []):
        status = j.get("status", {})
        if not status.get("completionTime"):
            continue
        if status.get("succeeded", 0) < 1 and status.get("failed", 0) < 1:
            continue
        if age_seconds(status.get("completionTime")) <= COMPLETED_JOB_AGE:
            continue
        # Skip if owned by CronJob
        owners = j.get("metadata", {}).get("ownerReferences", [])
        if any(o.get("kind") == "CronJob" for o in owners):
            continue
        if delete_resource("job", j["metadata"]["namespace"], j["metadata"]["name"], category="completed_job"):
            count += 1
    print(f"[INFO] Completed jobs: {count}")
    return count


def cleanup_cilium_identities():
    """Delete CiliumIdentity CRDs not referenced by any live CiliumEndpoint.

    Returns (stale_count, total_count). Cilium's operator has a built-in 15m
    GC, but a 2026-05-30 meltdown saga showed it can fall arbitrarily behind
    when the cascade kills the operator. This belt-and-suspenders catches
    accumulation before it saturates etcd. See TALOS-yyt.
    """
    if not CLEANUP_CILIUM_IDS:
        return (0, 0)
    print("[INFO] Cleaning stale CiliumIdentities...")

    ep_data = kubectl_json("get", "ciliumendpoints", "-A", "-o", "json")
    used = set()
    for ep in ep_data.get("items", []):
        ident = ep.get("status", {}).get("identity", {}).get("id")
        if ident is not None:
            used.add(str(ident))

    id_data = kubectl_json("get", "ciliumidentities", "-o", "json")
    id_items = id_data.get("items", [])
    all_ids = [i["metadata"]["name"] for i in id_items]
    # name -> labels map for diagnostics. metadata.labels carries the clean
    # k8s form (security-labels has "k8s:" prefixes that aren't useful in a UI).
    id_labels = {i["metadata"]["name"]: i.get("metadata", {}).get("labels", {}) for i in id_items}
    stale = [i for i in all_ids if i not in used]

    print(f"[INFO] CiliumIdentities: total={len(all_ids)} used={len(used)} stale={len(stale)}")

    if not stale:
        return (0, len(all_ids))

    # One pure-JSON line per stale identity so the Grafana/Loki panel can
    # parse it with `| json` and filter on `event="cilium_id_delete"`.
    # Kept distinct from the human-readable [INFO]/[DRY-RUN] lines above.
    for sid in stale:
        labels = id_labels.get(sid, {})
        print(json.dumps({
            "event": "cilium_id_delete",
            "id": sid,
            "namespace": labels.get("io.kubernetes.pod.namespace", ""),
            "app": labels.get("app.kubernetes.io/name") or labels.get("k8s-app") or "",
            "component": labels.get("app.kubernetes.io/component", ""),
            "serviceaccount": labels.get("io.cilium.k8s.policy.serviceaccount", ""),
        }))

    # batch deletes — 200 per kubectl call to avoid argv limits but stay fast
    deleted = 0
    BATCH = 200
    for i in range(0, len(stale), BATCH):
        batch = stale[i:i + BATCH]
        args = ["delete", "ciliumidentity", "--ignore-not-found", "--wait=false"] + batch
        if DRY_RUN:
            print(f"[DRY-RUN] Would delete {len(batch)} CiliumIdentities")
            deleted += len(batch)
            continue
        _, ok = kubectl(*args)
        if ok:
            deleted += len(batch)
    print(f"[INFO] CiliumIdentities deleted: {deleted}")
    return (deleted, len(all_ids))


def cleanup_orphan_replicasets():
    """Clean up orphaned ReplicaSets with 0 replicas."""
    if not CLEANUP_RS:
        return 0
    print("[INFO] Cleaning Orphaned ReplicaSets...")
    data = kubectl_json("get", "replicasets", "-A", "-o", "json")
    count = 0
    for rs in data.get("items", []):
        spec_replicas = rs.get("spec", {}).get("replicas", 1)
        status_replicas = rs.get("status", {}).get("replicas", 1)
        if spec_replicas == 0 and status_replicas == 0:
            if age_seconds(rs["metadata"].get("creationTimestamp")) > ORPHAN_RS_AGE:
                if delete_resource("replicaset", rs["metadata"]["namespace"], rs["metadata"]["name"], category="orphan_replicaset"):
                    count += 1
    print(f"[INFO] Orphaned ReplicaSets: {count}")
    return count


# Minimal protobuf encoder for Prometheus remote_write
def _encode_varint(n):
    """Encode integer as varint."""
    b = []
    while n > 127:
        b.append((n & 0x7F) | 0x80)
        n >>= 7
    b.append(n)
    return bytes(b)


def _encode_string(field, s):
    """Encode string field."""
    b = s.encode()
    return bytes([field << 3 | 2]) + _encode_varint(len(b)) + b


def _encode_label(name, value):
    """Encode a label pair."""
    inner = _encode_string(1, name) + _encode_string(2, value)
    return bytes([0x0A]) + _encode_varint(len(inner)) + inner


def _encode_sample(ts_ms, value):
    """Encode a sample (timestamp + value)."""
    # field 1: value (double), field 2: timestamp (int64)
    inner = bytes([0x09]) + struct.pack("<d", value) + bytes([0x10]) + _encode_varint(ts_ms)
    return bytes([0x12]) + _encode_varint(len(inner)) + inner


def _encode_timeseries(labels, ts_ms, value):
    """Encode a complete timeseries."""
    label_bytes = b"".join(_encode_label(k, v) for k, v in labels.items())
    sample_bytes = _encode_sample(ts_ms, value)
    inner = label_bytes + sample_bytes
    return bytes([0x0A]) + _encode_varint(len(inner)) + inner


def push_metrics_to_mimir(metrics):
    """Push metrics directly to Mimir via remote_write."""
    try:
        import snappy
    except ImportError:
        print("[WARN] python-snappy not installed, skipping metrics push")
        return

    ts_ms = int(time.time() * 1000)
    timeseries = []
    for name, value in metrics.items():
        labels = {"__name__": name, "job": "pod_cleanup", "instance": "talos00"}
        timeseries.append(_encode_timeseries(labels, ts_ms, float(value)))

    # WriteRequest message
    write_request = b"".join(timeseries)
    compressed = snappy.compress(write_request)

    try:
        req = Request(MIMIR_URL, data=compressed, method="POST")
        req.add_header("Content-Type", "application/x-protobuf")
        req.add_header("Content-Encoding", "snappy")
        req.add_header("X-Prometheus-Remote-Write-Version", "0.1.0")
        with urlopen(req, timeout=10) as resp:
            print(f"[INFO] Metrics pushed to Mimir ({resp.status})")
    except URLError as e:
        print(f"[WARN] Mimir push failed: {e}")


def main():
    start_time = time.time()
    print(f"=== Kubernetes Cleanup Job - {datetime.now(timezone.utc).isoformat()} ===")
    print(f"Mode: {'DRY-RUN' if DRY_RUN else 'LIVE'}")
    print()

    succeeded = cleanup_succeeded_pods()
    failed = cleanup_failed_pods()
    evicted = cleanup_evicted_pods()
    imagepull = cleanup_imagepull_pods()
    crashloop = cleanup_crashloop_pods()
    jobs = cleanup_completed_jobs()
    replicasets = cleanup_orphan_replicasets()
    cilium_deleted, cilium_total = cleanup_cilium_identities()

    end_time = time.time()
    duration = int(end_time - start_time)
    total = succeeded + failed + evicted + imagepull + crashloop + jobs + replicasets + cilium_deleted

    # status: 1 = OK (nothing to clean), 0 = WARNING (cleanup happened —
    # indicates label-filter gap or operator GC failing; humans should look)
    cilium_status_ok = 1 if cilium_deleted == 0 else 0

    print()
    print(f"=== Summary ({duration}s) ===")
    print(f"Succeeded:{succeeded} Failed:{failed} Evicted:{evicted} ImagePull:{imagepull} CrashLoop:{crashloop} Jobs:{jobs} RS:{replicasets} CiliumIDs:{cilium_deleted}/{cilium_total}")
    print(f"TOTAL: {total}")
    print(f"Cilium identity status: {'OK (no stale)' if cilium_status_ok else 'WARNING (cleanup occurred — check label filter)'}")

    push_metrics_to_mimir({
        "pod_cleanup_duration_seconds": duration,
        "pod_cleanup_dry_run": 1 if DRY_RUN else 0,
        "pod_cleanup_resources_total": total,
        "pod_cleanup_succeeded_pods": succeeded,
        "pod_cleanup_failed_pods": failed,
        "pod_cleanup_evicted_pods": evicted,
        "pod_cleanup_imagepull_pods": imagepull,
        "pod_cleanup_crashloop_pods": crashloop,
        "pod_cleanup_completed_jobs": jobs,
        "pod_cleanup_orphan_replicasets": replicasets,
        "pod_cleanup_cilium_identities_deleted": cilium_deleted,
        "pod_cleanup_cilium_identities_total": cilium_total,
        "pod_cleanup_cilium_identity_status": cilium_status_ok,
        "pod_cleanup_job_success": 1,
    })


if __name__ == "__main__":
    main()
