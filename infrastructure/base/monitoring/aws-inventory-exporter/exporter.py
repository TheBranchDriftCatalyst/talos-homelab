#!/usr/bin/env python3
"""AWS inventory + status exporter (TALOS-iymy follow-on).

Sweeps EVERY enabled AWS region and exposes a Prometheus /metrics snapshot of the FULL
account footprint — not just what's "on". If we provision it (via Crossplane or raw), it
shows here:
  compute: EC2 instances (any non-terminated state — running AND stopped)
  storage: EBS volumes (+ size), EBS snapshots (+ size), S3 buckets (+ size via CloudWatch)
  network: security groups, Elastic IPs (associated or not)
  identity: IAM users, roles, customer-managed policies, instance profiles
Plus an estimated RUNNING $/hr and an estimated IDLE storage $/mo (volumes/snapshots/S3/
unassociated EIPs — the "not on but still billing" spend), and an "unmanaged" flag for
resources with no crossplane tag (orphans / raw run-instances that live outside GitOps).

Read-only: only describe_*/list_*/get_* calls. Creds from the mounted aws-credentials secret.
Mirrors the cf-records-exporter shape: a background refresh thread + a stdlib HTTP server
serving the last snapshot, scraped by a PodMonitor. boto3 only (no prometheus_client).
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
REGIONS_ENV = os.environ.get("AWS_REGIONS", "").strip()  # restrict via comma-list, else ALL enabled

# Rough ON-DEMAND $/hr for the running-cost estimate (spot is less => conservative ceiling).
PRICE = {
    "g6e.12xlarge": 10.49, "g6e.4xlarge": 3.90, "g6e.2xlarge": 2.24, "g6e.xlarge": 1.86,
    "g5.12xlarge": 5.67, "g5.2xlarge": 1.21, "g5.xlarge": 1.006,
    "p4d.24xlarge": 32.77, "c5.4xlarge": 0.68, "c5.2xlarge": 0.34, "c5.xlarge": 0.17,
    "c5n.xlarge": 0.216, "m5.2xlarge": 0.384, "m5.xlarge": 0.192, "m5.large": 0.096,
    "t3.2xlarge": 0.3328, "t3.xlarge": 0.1664, "t3.large": 0.0832, "t3.medium": 0.0416,
    "t3.small": 0.0208, "t3.micro": 0.0104, "t3.nano": 0.0052,
}
# Rough $/GB-month for the idle-storage estimate, + $/month for an unassociated EIP.
EBS_GB_MO, SNAP_GB_MO, S3_GB_MO, EIP_UNASSOC_MO = 0.08, 0.05, 0.023, 3.60

_boto = Config(retries={"max_attempts": 3, "mode": "standard"}, connect_timeout=10, read_timeout=40)
_snapshot = ("# HELP aws_inventory_scrape_success 1 if the last sweep succeeded.\n"
             "# TYPE aws_inventory_scrape_success gauge\naws_inventory_scrape_success 0\n")
_lock = threading.Lock()


def _log(m):
    print(f"[aws-inventory-exporter] {m}", flush=True)


def _esc(v):
    return str(v).replace("\\", "\\\\").replace('"', '\\"').replace("\n", " ")


def _managed(tags):
    # upjet/Crossplane tag managed resources with crossplane-kind/-name/-providerconfig
    # (NOT crossplane.io/ — that was the bug that flagged every managed resource as an orphan).
    return "1" if any(k in ("crossplane-kind", "crossplane-name", "crossplane-providerconfig")
                      or k.startswith("crossplane.io/") for k in tags) else "0"


def _tagmap(taglist):
    return {t["Key"]: t["Value"] for t in (taglist or [])}


def _regions(ec2):
    if REGIONS_ENV:
        return [r.strip() for r in REGIONS_ENV.split(",") if r.strip()]
    resp = ec2.describe_regions(Filters=[{"Name": "opt-in-status",
                                          "Values": ["opt-in-not-required", "opted-in"]}])
    return sorted(r["RegionName"] for r in resp["Regions"])


def _s3_size(bucket, region):
    """(bytes, objects) from CloudWatch S3 daily metrics — cheap vs list-objects on a big bucket."""
    try:
        cw = boto3.client("cloudwatch", region_name=region or "us-east-1", config=_boto)

        def stat(metric, storage):
            r = cw.get_metric_statistics(
                Namespace="AWS/S3", MetricName=metric,
                Dimensions=[{"Name": "BucketName", "Value": bucket},
                            {"Name": "StorageType", "Value": storage}],
                StartTime=time.time() - 3 * 86400, EndTime=time.time(),
                Period=86400, Statistics=["Average"])
            pts = sorted(r.get("Datapoints", []), key=lambda p: p["Timestamp"])
            return pts[-1]["Average"] if pts else 0.0
        return stat("BucketSizeBytes", "StandardStorage"), stat("NumberOfObjects", "AllStorageTypes")
    except Exception:  # noqa: BLE001 — size is best-effort
        return 0.0, 0.0


def build_metrics():
    out = []

    def add(line):
        out.append(line)

    ok, regions_swept = 1, 0
    ec2_count, ebs_count = {}, {}
    cost_hr = {}                 # region -> running on-demand $/hr
    storage_gb = {"ebs": 0.0, "snapshot": 0.0, "s3": 0.0}
    eip_unassoc = 0
    counts = {"sg": 0, "snapshot": 0, "eip": 0}
    try:
        base = boto3.client("ec2", region_name="us-east-1", config=_boto)
        regions = _regions(base)
        for h in ("# HELP aws_ec2_instance_info An EC2 instance (value=1); state label incl. stopped.",
                  "# TYPE aws_ec2_instance_info gauge",
                  "# HELP aws_ebs_volume_size_gb An EBS volume; value = size GiB.",
                  "# TYPE aws_ebs_volume_size_gb gauge",
                  "# HELP aws_ebs_snapshot_size_gb A self-owned EBS snapshot; value = size GiB.",
                  "# TYPE aws_ebs_snapshot_size_gb gauge",
                  "# HELP aws_security_group_info A security group (value=1).",
                  "# TYPE aws_security_group_info gauge",
                  "# HELP aws_eip_info An Elastic IP (value=1); associated label.",
                  "# TYPE aws_eip_info gauge",
                  "# HELP aws_unmanaged_resource A live resource with no crossplane tag (orphan candidate).",
                  "# TYPE aws_unmanaged_resource gauge"):
            add(h)
        for region in regions:
            regions_swept += 1
            ec2 = boto3.client("ec2", region_name=region, config=_boto)
            # --- EC2 instances (running AND stopped) ---
            for page in ec2.get_paginator("describe_instances").paginate():
                for res in page["Reservations"]:
                    for inst in res["Instances"]:
                        state = inst["State"]["Name"]
                        if state in ("terminated", "shutting-down"):
                            continue
                        iid, itype = inst["InstanceId"], inst["InstanceType"]
                        tags = _tagmap(inst.get("Tags"))
                        name, managed = tags.get("Name", ""), _managed(tags)
                        life = "spot" if inst.get("InstanceLifecycle") == "spot" else "on-demand"
                        add(f'aws_ec2_instance_info{{id="{iid}",region="{region}",type="{itype}",'
                            f'state="{state}",name="{_esc(name)}",lifecycle="{life}",managed="{managed}"}} 1')
                        ec2_count[(region, itype, state)] = ec2_count.get((region, itype, state), 0) + 1
                        if state == "running":
                            cost_hr[region] = cost_hr.get(region, 0.0) + PRICE.get(itype, 0.0)
                        if managed == "0" and state != "terminated":
                            add(f'aws_unmanaged_resource{{type="ec2",id="{iid}",'
                                f'region="{region}",name="{_esc(name)}"}} 1')
            # --- EBS volumes ---
            for page in ec2.get_paginator("describe_volumes").paginate():
                for vol in page["Volumes"]:
                    vid, vstate, sz = vol["VolumeId"], vol["State"], vol["Size"]
                    managed = _managed(_tagmap(vol.get("Tags")))
                    add(f'aws_ebs_volume_size_gb{{id="{vid}",region="{region}",'
                        f'state="{vstate}",managed="{managed}"}} {sz}')
                    ebs_count[(region, vstate)] = ebs_count.get((region, vstate), 0) + 1
                    storage_gb["ebs"] += sz
                    if vstate == "available" and managed == "0":  # unattached + unmanaged = wasted spend
                        add(f'aws_unmanaged_resource{{type="ebs",id="{vid}",region="{region}",name=""}} 1')
            # --- EBS snapshots (self-owned only) ---
            for page in ec2.get_paginator("describe_snapshots").paginate(OwnerIds=["self"]):
                for snap in page["Snapshots"]:
                    sid, sz = snap["SnapshotId"], snap.get("VolumeSize", 0)
                    managed = _managed(_tagmap(snap.get("Tags")))
                    add(f'aws_ebs_snapshot_size_gb{{id="{sid}",region="{region}",managed="{managed}"}} {sz}')
                    counts["snapshot"] += 1
                    storage_gb["snapshot"] += sz
            # --- security groups ---
            for page in ec2.get_paginator("describe_security_groups").paginate():
                for sg in page["SecurityGroups"]:
                    managed = _managed(_tagmap(sg.get("Tags")))
                    add(f'aws_security_group_info{{id="{sg["GroupId"]}",region="{region}",'
                        f'name="{_esc(sg["GroupName"])}",vpc="{sg.get("VpcId","")}",managed="{managed}"}} 1')
                    counts["sg"] += 1
            # --- Elastic IPs ---
            for eip in ec2.describe_addresses().get("Addresses", []):
                assoc = "1" if eip.get("AssociationId") else "0"
                managed = _managed(_tagmap(eip.get("Tags")))
                add(f'aws_eip_info{{region="{region}",public_ip="{eip.get("PublicIp","")}",'
                    f'associated="{assoc}",managed="{managed}"}} 1')
                counts["eip"] += 1
                if assoc == "0":
                    eip_unassoc += 1
                    add(f'aws_unmanaged_resource{{type="eip-unassociated",'
                        f'id="{eip.get("AllocationId","")}",region="{region}",name=""}} 1')

        # --- global: S3 (+ size) + IAM (users/roles/policies/instance-profiles) ---
        add("# HELP aws_s3_bucket_info An S3 bucket (value=1).")
        add("# TYPE aws_s3_bucket_info gauge")
        add("# HELP aws_s3_bucket_bytes S3 bucket size in bytes (CloudWatch daily).")
        add("# TYPE aws_s3_bucket_bytes gauge")
        add("# HELP aws_s3_bucket_objects S3 bucket object count (CloudWatch daily).")
        add("# TYPE aws_s3_bucket_objects gauge")
        s3 = boto3.client("s3", config=_boto)
        for b in s3.list_buckets().get("Buckets", []):
            name = b["Name"]
            try:
                loc = s3.get_bucket_location(Bucket=name).get("LocationConstraint") or "us-east-1"
            except Exception:  # noqa: BLE001
                loc = "us-east-1"
            add(f'aws_s3_bucket_info{{name="{_esc(name)}",region="{loc}"}} 1')
            by, objs = _s3_size(name, loc)
            add(f'aws_s3_bucket_bytes{{name="{_esc(name)}"}} {int(by)}')
            add(f'aws_s3_bucket_objects{{name="{_esc(name)}"}} {int(objs)}')
            storage_gb["s3"] += by / (1024 ** 3)

        iam = boto3.client("iam", config=_boto)
        add("# HELP aws_iam_user_info An IAM user (value=1).")
        add("# TYPE aws_iam_user_info gauge")
        for page in iam.get_paginator("list_users").paginate():
            for u in page["Users"]:
                add(f'aws_iam_user_info{{name="{_esc(u["UserName"])}",path="{_esc(u.get("Path","/"))}"}} 1')
        add("# HELP aws_iam_role_info A customer IAM role (service-linked excluded) (value=1).")
        add("# TYPE aws_iam_role_info gauge")
        for page in iam.get_paginator("list_roles").paginate():
            for r in page["Roles"]:
                if r.get("Path", "/").startswith("/aws-service-role/"):
                    continue  # AWS service-linked roles are noise
                add(f'aws_iam_role_info{{name="{_esc(r["RoleName"])}",path="{_esc(r.get("Path","/"))}"}} 1')
        add("# HELP aws_iam_policy_info A customer-managed IAM policy (value=1).")
        add("# TYPE aws_iam_policy_info gauge")
        for page in iam.get_paginator("list_policies").paginate(Scope="Local"):  # customer-managed only
            for p in page["Policies"]:
                add(f'aws_iam_policy_info{{name="{_esc(p["PolicyName"])}",'
                    f'attached="{p.get("AttachmentCount",0)}"}} 1')
        add("# HELP aws_iam_instance_profile_info An IAM instance profile (value=1).")
        add("# TYPE aws_iam_instance_profile_info gauge")
        for page in iam.get_paginator("list_instance_profiles").paginate():
            for ip in page["InstanceProfiles"]:
                add(f'aws_iam_instance_profile_info{{name="{_esc(ip["InstanceProfileName"])}"}} 1')
    except Exception as e:  # noqa: BLE001 — surface as scrape_success=0, keep serving last good
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
    add("# HELP aws_resource_count Provisioned resource count by kind (incl. things that are off but present).")
    add("# TYPE aws_resource_count gauge")
    add(f'aws_resource_count{{kind="security_group"}} {counts["sg"]}')
    add(f'aws_resource_count{{kind="ebs_snapshot"}} {counts["snapshot"]}')
    add(f'aws_resource_count{{kind="elastic_ip"}} {counts["eip"]}')
    add(f'aws_resource_count{{kind="elastic_ip_unassociated"}} {eip_unassoc}')
    add("# HELP aws_estimated_cost_usd_per_hour Estimated ON-DEMAND $/hr of RUNNING instances.")
    add("# TYPE aws_estimated_cost_usd_per_hour gauge")
    total = 0.0
    for region, c in sorted(cost_hr.items()):
        add(f'aws_estimated_cost_usd_per_hour{{region="{region}"}} {c:.4f}')
        total += c
    add(f'aws_estimated_cost_usd_per_hour{{region="all"}} {total:.4f}')
    add("# HELP aws_estimated_storage_cost_usd_per_month Idle/standing spend: EBS+snapshots+S3+unassoc EIPs.")
    add("# TYPE aws_estimated_storage_cost_usd_per_month gauge")
    add(f'aws_estimated_storage_cost_usd_per_month{{kind="ebs"}} {storage_gb["ebs"] * EBS_GB_MO:.2f}')
    add(f'aws_estimated_storage_cost_usd_per_month{{kind="ebs_snapshot"}} {storage_gb["snapshot"] * SNAP_GB_MO:.2f}')
    add(f'aws_estimated_storage_cost_usd_per_month{{kind="s3"}} {storage_gb["s3"] * S3_GB_MO:.2f}')
    add(f'aws_estimated_storage_cost_usd_per_month{{kind="elastic_ip"}} {eip_unassoc * EIP_UNASSOC_MO:.2f}')
    stor_total = (storage_gb["ebs"] * EBS_GB_MO + storage_gb["snapshot"] * SNAP_GB_MO
                  + storage_gb["s3"] * S3_GB_MO + eip_unassoc * EIP_UNASSOC_MO)
    add(f'aws_estimated_storage_cost_usd_per_month{{kind="all"}} {stor_total:.2f}')
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
    _log(f"serving /metrics on :{PORT} (interval {SCRAPE_INTERVAL}s, regions={REGIONS_ENV or 'ALL'})")
    ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
