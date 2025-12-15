#!/usr/bin/env python3
"""Kubernetes resource cleanup script with metrics."""

import json
import os
import subprocess
import time
from datetime import datetime, timezone
from urllib.request import urlopen, Request
from urllib.error import URLError

# Config from environment
DRY_RUN = os.environ.get("DRY_RUN", "false").lower() == "true"
EXCLUDED_NAMESPACES = set(os.environ.get("EXCLUDED_NAMESPACES", "kube-system,kube-public,kube-node-lease").split(","))
PUSHGATEWAY_URL = os.environ.get("PUSHGATEWAY_URL", "http://prometheus-pushgateway.monitoring.svc.cluster.local:9091")

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
    except:
        return 0


def age_seconds(ts):
    """Get age in seconds from timestamp."""
    return time.time() - parse_time(ts)


def delete_resource(kind, namespace, name):
    """Delete a resource, returns True if deleted."""
    if namespace in EXCLUDED_NAMESPACES:
        return False

    if DRY_RUN:
        print(f"[DRY-RUN] Would delete {kind} {namespace}/{name}")
        return True

    _, ok = kubectl("delete", kind, "-n", namespace, name, "--ignore-not-found", "--wait=false")
    if ok:
        print(f"[DELETE] {kind} {namespace}/{name}")
    return ok


def cleanup_succeeded_pods():
    """Clean up succeeded pods."""
    if not CLEANUP_SUCCEEDED:
        return 0
    print("[INFO] Cleaning Succeeded Pods...")
    data = kubectl_json("get", "pods", "-A", "--field-selector=status.phase==Succeeded", "-o", "json")
    count = sum(1 for p in data.get("items", []) if delete_resource("pod", p["metadata"]["namespace"], p["metadata"]["name"]))
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
            if delete_resource("pod", p["metadata"]["namespace"], p["metadata"]["name"]):
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
            if delete_resource("pod", p["metadata"]["namespace"], p["metadata"]["name"]):
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
                    if delete_resource("pod", p["metadata"]["namespace"], p["metadata"]["name"]):
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
                        if delete_resource("pod", p["metadata"]["namespace"], p["metadata"]["name"]):
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
        if delete_resource("job", j["metadata"]["namespace"], j["metadata"]["name"]):
            count += 1
    print(f"[INFO] Completed jobs: {count}")
    return count


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
                if delete_resource("replicaset", rs["metadata"]["namespace"], rs["metadata"]["name"]):
                    count += 1
    print(f"[INFO] Orphaned ReplicaSets: {count}")
    return count


def push_metrics(metrics):
    """Push metrics to Pushgateway."""
    lines = [f"{k} {v}" for k, v in metrics.items()]
    body = "\n".join(lines) + "\n"
    url = f"{PUSHGATEWAY_URL}/metrics/job/pod_cleanup/instance/talos00"
    try:
        req = Request(url, data=body.encode(), method="POST")
        req.add_header("Content-Type", "text/plain")
        with urlopen(req, timeout=10) as resp:
            print("Metrics pushed")
    except URLError as e:
        print(f"Metrics push failed: {e}")


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

    end_time = time.time()
    duration = int(end_time - start_time)
    total = succeeded + failed + evicted + imagepull + crashloop + jobs + replicasets

    print()
    print(f"=== Summary ({duration}s) ===")
    print(f"Succeeded:{succeeded} Failed:{failed} Evicted:{evicted} ImagePull:{imagepull} CrashLoop:{crashloop} Jobs:{jobs} RS:{replicasets}")
    print(f"TOTAL: {total}")

    push_metrics({
        "pod_cleanup_last_run_timestamp_seconds": int(end_time),
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
        "pod_cleanup_job_success": 1,
    })


if __name__ == "__main__":
    main()
