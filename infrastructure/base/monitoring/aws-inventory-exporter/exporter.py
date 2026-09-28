#!/usr/bin/env python3
"""AWS inventory + status exporter (TALOS-iymy follow-on).

Sweeps EVERY enabled AWS region and exposes a Prometheus /metrics snapshot of what
actually exists in the account — EC2 instances, EBS volumes, S3 buckets, IAM users —
plus an estimated running $/hr and an "unmanaged" flag (resources with no Crossplane
tag). The point is cost + orphan visibility: transient boxes launched via raw
run-instances (seeders, builders, red-team vantages) live OUTSIDE GitOps and nothing
else in Grafana sees them. All-regions by default so an orphan can't hide in a region
we don't normally use.

Read-only: only describe_*/list_* calls. Creds from the mounted aws-credentials secret
(env AWS_SHARED_CREDENTIALS_FILE). Mirrors the external-dns cf-records-exporter shape:
a background refresh thread + a stdlib HTTP server serving the last snapshot, scraped
by a PodMonitor. No prometheus_client dep (boto3 only).
"""
import os
import threading
import time
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import boto3
from botocore.config import Config

SCRAPE_INTERVAL = int(os.environ.get("SCRAPE_INTERVAL", "600"))  # 10 min; AWS state is slow-moving
PORT = int(os.environ.get("METRICS_PORT", "9100"))
# Restrict to a comma-list of regions via AWS_REGIONS, else sweep every enabled region.
REGIONS_ENV = os.environ.get("AWS_REGIONS", "").strip()

# Rough ON-DEMAND $/hr (us-east/us-west), for a "am I burning money" estimate. Spot is
# lower, so this is a conservative ceiling. Unknown types fall back to 0 (labelled).
PRICE = {
    "g6e.12xlarge": 10.49, "g6e.4xlarge": 3.90, "g6e.2xlarge": 2.24, "g6e.xlarge": 1.86,
    "g5.12xlarge": 5.67, "g5.2xlarge": 1.21, "g5.xlarge": 1.006,
    "p4d.24xlarge": 32.77, "c5.4xlarge": 0.68, "c5.2xlarge": 0.34, "c5.xlarge": 0.17,
    "c5n.xlarge": 0.216, "m5.2xlarge": 0.384, "m5.xlarge": 0.192, "m5.large": 0.096,
    "t3.2xlarge": 0.3328, "t3.xlarge": 0.1664, "t3.large": 0.0832, "t3.medium": 0.0416,
    "t3.small": 0.0208, "t3.micro": 0.0104, "t3.nano": 0.0052,
}

_boto = Config(retries={"max_attempts": 3, "mode": "standard"}, connect_timeout=10, read_timeout=30)
_snapshot = "# HELP aws_inventory_scrape_success 1 if the last sweep succeeded.\n# TYPE aws_inventory_scrape_success gauge\naws_inventory_scrape_success 0\n"
_lock = threading.Lock()


def _log(m):
    print(f"[aws-inventory-exporter] {m}", flush=True)


def _esc(v):
    return str(v).replace("\\", "\\\\").replace('"', '\\"').replace("\n", " ")


def _regions(ec2):
    if REGIONS_ENV:
        return [r.strip() for r in REGIONS_ENV.split(",") if r.strip()]
    resp = ec2.describe_regions(Filters=[{"Name": "opt-in-status",
                                          "Values": ["opt-in-not-required", "opted-in"]}])
    return sorted(r["RegionName"] for r in resp["Regions"])


def _managed(tags):
    # A resource is "managed" if Crossplane/our GitOps owns it (carries a crossplane tag).
    return "1" if any(k.startswith("crossplane.io/") for k in tags) else "0"


def build_metrics():
    out = []

    def add(line):
        out.append(line)

    ok = 1
    ec2_count = {}       # (region,type,state) -> n
    ebs_count = {}       # (region,state) -> n
    cost = {}            # region -> $/hr (running, on-demand estimate)
    regions_swept = 0
    try:
        base = boto3.client("ec2", region_name="us-east-1", config=_boto)
        regions = _regions(base)
        add("# HELP aws_ec2_instance_info An EC2 instance (value=1); labels carry its state.")
        add("# TYPE aws_ec2_instance_info gauge")
        add("# HELP aws_unmanaged_resource A live resource with no crossplane tag (orphan candidate).")
        add("# TYPE aws_unmanaged_resource gauge")
        add("# HELP aws_ebs_volume_size_gb An EBS volume; value = size in GiB.")
        add("# TYPE aws_ebs_volume_size_gb gauge")
        for region in regions:
            regions_swept += 1
            ec2 = boto3.client("ec2", region_name=region, config=_boto)
            # --- EC2 instances ---
            for page in ec2.get_paginator("describe_instances").paginate():
                for res in page["Reservations"]:
                    for inst in res["Instances"]:
                        state = inst["State"]["Name"]
                        if state in ("terminated", "shutting-down"):
                            continue
                        iid, itype = inst["InstanceId"], inst["InstanceType"]
                        tags = {t["Key"]: t["Value"] for t in inst.get("Tags", [])}
                        name, managed = tags.get("Name", ""), _managed(tags)
                        life = "spot" if inst.get("InstanceLifecycle") == "spot" else "on-demand"
                        add(f'aws_ec2_instance_info{{id="{iid}",region="{region}",type="{itype}",'
                            f'state="{state}",name="{_esc(name)}",lifecycle="{life}",managed="{managed}"}} 1')
                        ec2_count[(region, itype, state)] = ec2_count.get((region, itype, state), 0) + 1
                        if state == "running":
                            cost[region] = cost.get(region, 0.0) + PRICE.get(itype, 0.0)
                            if managed == "0":
                                add(f'aws_unmanaged_resource{{type="ec2",id="{iid}",'
                                    f'region="{region}",name="{_esc(name)}"}} 1')
            # --- EBS volumes ---
            for page in ec2.get_paginator("describe_volumes").paginate():
                for vol in page["Volumes"]:
                    vid, vstate = vol["VolumeId"], vol["State"]
                    vtags = {t["Key"]: t["Value"] for t in vol.get("Tags", [])}
                    managed = _managed(vtags)
                    add(f'aws_ebs_volume_size_gb{{id="{vid}",region="{region}",'
                        f'state="{vstate}",managed="{managed}"}} {vol["Size"]}')
                    ebs_count[(region, vstate)] = ebs_count.get((region, vstate), 0) + 1
                    if vstate == "available" and managed == "0":  # unattached + unmanaged = wasted spend
                        add(f'aws_unmanaged_resource{{type="ebs",id="{vid}",region="{region}",name=""}} 1')
        # --- global: S3 + IAM ---
        add("# HELP aws_s3_bucket_info An S3 bucket (value=1).")
        add("# TYPE aws_s3_bucket_info gauge")
        s3 = boto3.client("s3", config=_boto)
        for b in s3.list_buckets().get("Buckets", []):
            add(f'aws_s3_bucket_info{{name="{_esc(b["Name"])}"}} 1')
        add("# HELP aws_iam_user_info An IAM user (value=1).")
        add("# TYPE aws_iam_user_info gauge")
        iam = boto3.client("iam", config=_boto)
        for page in iam.get_paginator("list_users").paginate():
            for u in page["Users"]:
                add(f'aws_iam_user_info{{name="{_esc(u["UserName"])}"}} 1')
    except Exception as e:  # noqa: BLE001 — surface as scrape_success=0, keep serving
        ok = 0
        _log(f"sweep failed: {e}\n{traceback.format_exc()}")

    # --- rollups ---
    add("# HELP aws_ec2_instances Instance count by region/type/state.")
    add("# TYPE aws_ec2_instances gauge")
    for (region, itype, state), n in sorted(ec2_count.items()):
        add(f'aws_ec2_instances{{region="{region}",type="{itype}",state="{state}"}} {n}')
    add("# HELP aws_ebs_volumes EBS volume count by region/state.")
    add("# TYPE aws_ebs_volumes gauge")
    for (region, state), n in sorted(ebs_count.items()):
        add(f'aws_ebs_volumes{{region="{region}",state="{state}"}} {n}')
    add("# HELP aws_estimated_cost_usd_per_hour Estimated ON-DEMAND $/hr of RUNNING instances (spot is less).")
    add("# TYPE aws_estimated_cost_usd_per_hour gauge")
    total = 0.0
    for region, c in sorted(cost.items()):
        add(f'aws_estimated_cost_usd_per_hour{{region="{region}"}} {c:.4f}')
        total += c
    add(f'aws_estimated_cost_usd_per_hour{{region="all"}} {total:.4f}')
    add("# HELP aws_inventory_regions_swept Number of regions swept this scrape.")
    add("# TYPE aws_inventory_regions_swept gauge")
    add(f"aws_inventory_regions_swept {regions_swept}")
    add("# HELP aws_inventory_scrape_success 1 if the last sweep succeeded.")
    add("# TYPE aws_inventory_scrape_success gauge")
    add(f"aws_inventory_scrape_success {ok}")
    add("# HELP aws_inventory_last_scrape_timestamp_seconds Unix time of the last sweep.")
    add("# TYPE aws_inventory_last_scrape_timestamp_seconds gauge")
    add(f"aws_inventory_last_scrape_timestamp_seconds {int(time.time())}")
    return "\n".join(out) + "\n"


def _refresh_loop():
    global _snapshot
    while True:
        try:
            snap = build_metrics()
            with _lock:
                _snapshot = snap
            _log(f"snapshot refreshed ({snap.count(chr(10))} lines)")
        except Exception as e:  # noqa: BLE001
            _log(f"refresh loop error: {e}")
        time.sleep(SCRAPE_INTERVAL)


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path not in ("/metrics", "/"):
            self.send_response(404)
            self.end_headers()
            return
        with _lock:
            body = _snapshot.encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/plain; version=0.0.4")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a):  # quiet
        pass


if __name__ == "__main__":
    threading.Thread(target=_refresh_loop, daemon=True).start()
    _log(f"serving /metrics on :{PORT} (interval {SCRAPE_INTERVAL}s, "
         f"regions={REGIONS_ENV or 'ALL'})")
    ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
