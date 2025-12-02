#!/usr/bin/env python3
"""
Resource Optimization Report Generator

Generates a comprehensive resource usage and optimization report by querying
Prometheus metrics and kubectl for cluster resource allocation.

Usage:
    ./scripts/generate-resource-report.py [--output docs/RESOURCE-OPTIMIZATION.md]

Requirements:
    - kubectl configured with cluster access
    - Port-forward to Prometheus: kubectl port-forward -n monitoring svc/kube-prometheus-stack-prometheus 9090:9090
    - Or use --prometheus-url to specify a different endpoint
"""

import argparse
import json
import subprocess
import sys
import urllib.request
import urllib.parse
from datetime import datetime
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple


@dataclass
class PodResources:
    namespace: str
    pod: str
    cpu_request: float  # millicores
    cpu_limit: float
    cpu_usage: float
    cpu_p95: float
    mem_request: float  # MiB
    mem_limit: float
    mem_usage: float
    mem_p95: float

    @property
    def cpu_efficiency(self) -> float:
        if self.cpu_request == 0:
            return 0
        return (self.cpu_usage / self.cpu_request) * 100

    @property
    def mem_efficiency(self) -> float:
        if self.mem_request == 0:
            return 0
        return (self.mem_usage / self.mem_request) * 100

    @property
    def suggested_cpu_request(self) -> float:
        """P95 + 20% headroom, minimum 5m"""
        return max(5, self.cpu_p95 * 1.2)

    @property
    def suggested_mem_request(self) -> float:
        """P95 + 20% headroom, minimum 10Mi"""
        return max(10, self.mem_p95 * 1.2)

    @property
    def cpu_savings(self) -> float:
        return self.cpu_request - self.suggested_cpu_request

    @property
    def mem_savings(self) -> float:
        return self.mem_request - self.suggested_mem_request


def query_prometheus(base_url: str, query: str) -> Dict:
    """Execute a PromQL query and return results."""
    url = f"{base_url}/api/v1/query?query={urllib.parse.quote(query)}"
    try:
        with urllib.request.urlopen(url, timeout=30) as response:
            data = json.loads(response.read().decode())
            if data["status"] == "success":
                return {
                    (r["metric"].get("namespace", ""), r["metric"].get("pod", "")): float(r["value"][1])
                    for r in data["data"]["result"]
                }
            else:
                print(f"Query error: {data.get('error', 'unknown')}", file=sys.stderr)
                return {}
    except Exception as e:
        print(f"Error querying Prometheus: {e}", file=sys.stderr)
        return {}


def get_kubectl_resources() -> Tuple[Dict, Dict, Dict]:
    """Get node capacity and pod resource specs from kubectl."""
    # Node info
    node_info = {}
    try:
        result = subprocess.run(
            ["kubectl", "get", "nodes", "-o", "json"],
            capture_output=True, text=True, check=True
        )
        nodes = json.loads(result.stdout)
        for node in nodes["items"]:
            name = node["metadata"]["name"]
            capacity = node["status"]["capacity"]
            allocatable = node["status"]["allocatable"]
            node_info[name] = {
                "cpu_capacity": parse_cpu(capacity.get("cpu", "0")),
                "mem_capacity": parse_memory(capacity.get("memory", "0")),
                "cpu_allocatable": parse_cpu(allocatable.get("cpu", "0")),
                "mem_allocatable": parse_memory(allocatable.get("memory", "0")),
            }
    except Exception as e:
        print(f"Error getting node info: {e}", file=sys.stderr)

    # Node usage
    node_usage = {}
    try:
        result = subprocess.run(
            ["kubectl", "top", "nodes", "--no-headers"],
            capture_output=True, text=True, check=True
        )
        for line in result.stdout.strip().split("\n"):
            parts = line.split()
            if len(parts) >= 5:
                name = parts[0]
                node_usage[name] = {
                    "cpu_used": parse_cpu(parts[1]),
                    "cpu_percent": int(parts[2].rstrip("%")),
                    "mem_used": parse_memory(parts[3]),
                    "mem_percent": int(parts[4].rstrip("%")),
                }
    except Exception as e:
        print(f"Error getting node usage: {e}", file=sys.stderr)

    # Describe node for allocation summary
    allocation = {}
    try:
        result = subprocess.run(
            ["kubectl", "describe", "nodes"],
            capture_output=True, text=True, check=True
        )
        # Parse the allocation section
        in_allocation = False
        for line in result.stdout.split("\n"):
            if "Allocated resources:" in line:
                in_allocation = True
                continue
            if in_allocation and "cpu" in line.lower() and "%" in line:
                parts = line.split()
                for i, p in enumerate(parts):
                    if "m" in p and "(" in parts[i+1] if i+1 < len(parts) else False:
                        allocation["cpu_requests"] = parse_cpu(p)
                        allocation["cpu_requests_pct"] = int(parts[i+1].strip("()%"))
                        break
            if in_allocation and "memory" in line.lower() and "%" in line:
                parts = line.split()
                for i, p in enumerate(parts):
                    if ("Mi" in p or "Gi" in p) and "(" in (parts[i+1] if i+1 < len(parts) else ""):
                        allocation["mem_requests"] = parse_memory(p)
                        allocation["mem_requests_pct"] = int(parts[i+1].strip("()%"))
                        break
                in_allocation = False
    except Exception as e:
        print(f"Error getting allocation: {e}", file=sys.stderr)

    return node_info, node_usage, allocation


def parse_cpu(value: str) -> float:
    """Parse CPU value to millicores."""
    value = value.strip()
    if value.endswith("m"):
        return float(value[:-1])
    elif value.endswith("n"):
        return float(value[:-1]) / 1_000_000
    else:
        return float(value) * 1000


def parse_memory(value: str) -> float:
    """Parse memory value to MiB."""
    value = value.strip()
    if value.endswith("Ki"):
        return float(value[:-2]) / 1024
    elif value.endswith("Mi"):
        return float(value[:-2])
    elif value.endswith("Gi"):
        return float(value[:-2]) * 1024
    elif value.endswith("Ti"):
        return float(value[:-2]) * 1024 * 1024
    elif value.endswith("K"):
        return float(value[:-1]) / 1024
    elif value.endswith("M"):
        return float(value[:-1])
    elif value.endswith("G"):
        return float(value[:-1]) * 1024
    else:
        # Assume bytes
        return float(value) / 1024 / 1024


def format_cpu(millicores: float) -> str:
    """Format CPU in millicores."""
    if millicores >= 1000:
        return f"{millicores/1000:.1f}"
    return f"{millicores:.0f}m"


def format_memory(mib: float) -> str:
    """Format memory in MiB or GiB."""
    if mib >= 1024:
        return f"{mib/1024:.1f}Gi"
    return f"{mib:.0f}Mi"


def collect_pod_resources(prometheus_url: str) -> List[PodResources]:
    """Collect all resource metrics for pods."""
    print("Querying Prometheus for metrics...", file=sys.stderr)

    # Query all metrics
    queries = {
        "cpu_usage": 'sum(rate(container_cpu_usage_seconds_total{container!="",container!="POD"}[12h])) by (namespace,pod)',
        "cpu_requests": 'sum(kube_pod_container_resource_requests{resource="cpu"}) by (namespace,pod)',
        "cpu_limits": 'sum(kube_pod_container_resource_limits{resource="cpu"}) by (namespace,pod)',
        "cpu_p95": 'quantile_over_time(0.95, sum(rate(container_cpu_usage_seconds_total{container!="",container!="POD"}[5m])) by (namespace,pod)[24h:5m])',
        "mem_usage": 'sum(container_memory_working_set_bytes{container!="",container!="POD"}) by (namespace,pod)',
        "mem_requests": 'sum(kube_pod_container_resource_requests{resource="memory"}) by (namespace,pod)',
        "mem_limits": 'sum(kube_pod_container_resource_limits{resource="memory"}) by (namespace,pod)',
        "mem_p95": 'quantile_over_time(0.95, sum(container_memory_working_set_bytes{container!="",container!="POD"}) by (namespace,pod)[24h:5m])',
    }

    results = {}
    for name, query in queries.items():
        print(f"  Querying {name}...", file=sys.stderr)
        results[name] = query_prometheus(prometheus_url, query)

    # Combine into PodResources objects
    all_pods = set()
    for metric_data in results.values():
        all_pods.update(metric_data.keys())

    pods = []
    for ns, pod in sorted(all_pods):
        if not ns or not pod:
            continue

        # Skip completed jobs and init containers
        if any(x in pod for x in ["-init-", "pod-cleanup-"]):
            continue

        pr = PodResources(
            namespace=ns,
            pod=pod,
            cpu_request=results["cpu_requests"].get((ns, pod), 0) * 1000,  # to millicores
            cpu_limit=results["cpu_limits"].get((ns, pod), 0) * 1000,
            cpu_usage=results["cpu_usage"].get((ns, pod), 0) * 1000,
            cpu_p95=results["cpu_p95"].get((ns, pod), 0) * 1000,
            mem_request=results["mem_requests"].get((ns, pod), 0) / 1024 / 1024,  # to MiB
            mem_limit=results["mem_limits"].get((ns, pod), 0) / 1024 / 1024,
            mem_usage=results["mem_usage"].get((ns, pod), 0) / 1024 / 1024,
            mem_p95=results["mem_p95"].get((ns, pod), 0) / 1024 / 1024,
        )
        pods.append(pr)

    return pods


def generate_report(pods: List[PodResources], node_info: Dict, node_usage: Dict, allocation: Dict) -> str:
    """Generate the markdown report."""
    now = datetime.now().strftime("%Y-%m-%d %H:%M")

    # Calculate totals
    total_cpu_requests = sum(p.cpu_request for p in pods)
    total_cpu_usage = sum(p.cpu_usage for p in pods)
    total_mem_requests = sum(p.mem_request for p in pods)
    total_mem_usage = sum(p.mem_usage for p in pods)
    total_suggested_cpu = sum(p.suggested_cpu_request for p in pods)
    total_suggested_mem = sum(p.suggested_mem_request for p in pods)

    # Get node capacity (first node)
    node_name = list(node_info.keys())[0] if node_info else "unknown"
    node = node_info.get(node_name, {})
    usage = node_usage.get(node_name, {})

    report = f"""# Resource Optimization Analysis

**Generated:** {now}
**Data Period:** 12-24 hours of metrics collection
**Cluster:** {node_name} (single-node)

## Executive Summary

| Metric | Value |
|--------|-------|
| **Node Capacity** | {format_cpu(node.get('cpu_capacity', 0))} CPU cores, {format_memory(node.get('mem_capacity', 0))} RAM |
| **Allocatable** | {format_cpu(node.get('cpu_allocatable', 0))} CPU, {format_memory(node.get('mem_allocatable', 0))} RAM |
| **Current Usage** | {usage.get('cpu_percent', 0)}% CPU ({format_cpu(usage.get('cpu_used', 0))}), {usage.get('mem_percent', 0)}% memory ({format_memory(usage.get('mem_used', 0))}) |
| **Requests** | {allocation.get('cpu_requests_pct', 0)}% CPU ({format_cpu(allocation.get('cpu_requests', 0))}), {allocation.get('mem_requests_pct', 0)}% memory ({format_memory(allocation.get('mem_requests', 0))}) |

### Optimization Potential

| Resource | Current Requests | Suggested Requests | Potential Savings |
|----------|------------------|--------------------|--------------------|
| CPU | {format_cpu(total_cpu_requests)} | {format_cpu(total_suggested_cpu)} | **{format_cpu(total_cpu_requests - total_suggested_cpu)}** |
| Memory | {format_memory(total_mem_requests)} | {format_memory(total_suggested_mem)} | **{format_memory(total_mem_requests - total_suggested_mem)}** |

---

## CPU Optimization Details

### Workloads by CPU Efficiency (Lowest First - Most Over-provisioned)

| Namespace | Pod | Request | Usage (12h) | P95 (24h) | Efficiency | Suggested | Savings |
|-----------|-----|---------|-------------|-----------|------------|-----------|---------|
"""

    # Sort by CPU efficiency (lowest first = most over-provisioned)
    cpu_sorted = sorted([p for p in pods if p.cpu_request > 0], key=lambda p: p.cpu_efficiency)

    for p in cpu_sorted[:40]:
        report += f"| {p.namespace} | {p.pod[:40]} | {format_cpu(p.cpu_request)} | {format_cpu(p.cpu_usage)} | {format_cpu(p.cpu_p95)} | {p.cpu_efficiency:.0f}% | {format_cpu(p.suggested_cpu_request)} | {format_cpu(p.cpu_savings)} |\n"

    report += f"""
---

## Memory Optimization Details

### Workloads by Memory Efficiency (Lowest First - Most Over-provisioned)

| Namespace | Pod | Request | Usage | P95 (24h) | Efficiency | Suggested | Savings |
|-----------|-----|---------|-------|-----------|------------|-----------|---------|
"""

    # Sort by memory efficiency
    mem_sorted = sorted([p for p in pods if p.mem_request > 0], key=lambda p: p.mem_efficiency)

    for p in mem_sorted[:40]:
        report += f"| {p.namespace} | {p.pod[:40]} | {format_memory(p.mem_request)} | {format_memory(p.mem_usage)} | {format_memory(p.mem_p95)} | {p.mem_efficiency:.0f}% | {format_memory(p.suggested_mem_request)} | {format_memory(p.mem_savings)} |\n"

    report += f"""
---

## Critical Under-provisioned Workloads

These workloads are using >100% of their requests and may need increases:

| Namespace | Pod | CPU Req | CPU P95 | Mem Req | Mem P95 | Status |
|-----------|-----|---------|---------|---------|---------|--------|
"""

    # Find under-provisioned
    under_provisioned = [p for p in pods if (p.cpu_request > 0 and p.cpu_p95 > p.cpu_request) or
                                             (p.mem_request > 0 and p.mem_p95 > p.mem_request)]
    under_provisioned.sort(key=lambda p: max(p.cpu_p95/max(p.cpu_request,1), p.mem_p95/max(p.mem_request,1)), reverse=True)

    for p in under_provisioned[:20]:
        cpu_status = "CPU Over" if p.cpu_p95 > p.cpu_request else ""
        mem_status = "MEM Over" if p.mem_p95 > p.mem_request else ""
        status = ", ".join(filter(None, [cpu_status, mem_status]))
        report += f"| {p.namespace} | {p.pod[:40]} | {format_cpu(p.cpu_request)} | {format_cpu(p.cpu_p95)} | {format_memory(p.mem_request)} | {format_memory(p.mem_p95)} | {status} |\n"

    report += f"""
---

## Namespace Summary

| Namespace | Pods | CPU Request | CPU Usage | Mem Request | Mem Usage |
|-----------|------|-------------|-----------|-------------|-----------|
"""

    # Group by namespace
    ns_stats = {}
    for p in pods:
        if p.namespace not in ns_stats:
            ns_stats[p.namespace] = {"pods": 0, "cpu_req": 0, "cpu_use": 0, "mem_req": 0, "mem_use": 0}
        ns_stats[p.namespace]["pods"] += 1
        ns_stats[p.namespace]["cpu_req"] += p.cpu_request
        ns_stats[p.namespace]["cpu_use"] += p.cpu_usage
        ns_stats[p.namespace]["mem_req"] += p.mem_request
        ns_stats[p.namespace]["mem_use"] += p.mem_usage

    for ns, stats in sorted(ns_stats.items(), key=lambda x: x[1]["mem_req"], reverse=True):
        report += f"| {ns} | {stats['pods']} | {format_cpu(stats['cpu_req'])} | {format_cpu(stats['cpu_use'])} | {format_memory(stats['mem_req'])} | {format_memory(stats['mem_use'])} |\n"

    report += f"""
---

## CSV Export

To export this data as CSV, run:
```bash
./scripts/generate-resource-report.py --csv > resource-report.csv
```

## Queries Reference

```promql
# CPU efficiency
sum(rate(container_cpu_usage_seconds_total{{container!="",container!="POD"}}[12h])) by (namespace,pod)

# Memory efficiency
sum(container_memory_working_set_bytes{{container!="",container!="POD"}}) by (namespace,pod)

# P95 CPU for recommendations
quantile_over_time(0.95, sum(rate(container_cpu_usage_seconds_total[5m])) by (namespace,pod)[24h:5m])

# P95 Memory for recommendations
quantile_over_time(0.95, sum(container_memory_working_set_bytes) by (namespace,pod)[24h:5m])
```
"""

    return report


def generate_csv(pods: List[PodResources]) -> str:
    """Generate CSV output."""
    lines = ["namespace,pod,cpu_request_m,cpu_usage_m,cpu_p95_m,cpu_suggested_m,cpu_savings_m,mem_request_mi,mem_usage_mi,mem_p95_mi,mem_suggested_mi,mem_savings_mi,cpu_efficiency_pct,mem_efficiency_pct"]

    for p in sorted(pods, key=lambda x: (x.namespace, x.pod)):
        if not p.cpu_request and not p.mem_request:
            continue
        lines.append(f"{p.namespace},{p.pod},{p.cpu_request:.0f},{p.cpu_usage:.1f},{p.cpu_p95:.1f},{p.suggested_cpu_request:.0f},{p.cpu_savings:.0f},{p.mem_request:.0f},{p.mem_usage:.1f},{p.mem_p95:.1f},{p.suggested_mem_request:.0f},{p.mem_savings:.0f},{p.cpu_efficiency:.0f},{p.mem_efficiency:.0f}")

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="Generate resource optimization report")
    parser.add_argument("--prometheus-url", default="http://localhost:9090",
                       help="Prometheus URL (default: http://localhost:9090)")
    parser.add_argument("--output", "-o", default=None,
                       help="Output file (default: stdout)")
    parser.add_argument("--csv", action="store_true",
                       help="Output as CSV instead of markdown")
    args = parser.parse_args()

    # Check Prometheus connectivity
    print(f"Connecting to Prometheus at {args.prometheus_url}...", file=sys.stderr)
    test = query_prometheus(args.prometheus_url, "up")
    if not test:
        print("Error: Cannot connect to Prometheus. Make sure port-forward is running:", file=sys.stderr)
        print("  kubectl port-forward -n monitoring svc/kube-prometheus-stack-prometheus 9090:9090", file=sys.stderr)
        sys.exit(1)
    print(f"Connected! Found {len(test)} metrics.", file=sys.stderr)

    # Collect data
    pods = collect_pod_resources(args.prometheus_url)
    print(f"Collected metrics for {len(pods)} pods.", file=sys.stderr)

    node_info, node_usage, allocation = get_kubectl_resources()

    # Generate output
    if args.csv:
        output = generate_csv(pods)
    else:
        output = generate_report(pods, node_info, node_usage, allocation)

    # Write output
    if args.output:
        with open(args.output, "w") as f:
            f.write(output)
        print(f"Report written to {args.output}", file=sys.stderr)
    else:
        print(output)


if __name__ == "__main__":
    main()
