#!/usr/bin/env python3
"""AWS account-wide inventory exporter — three buckets, exactly (TALOS-hnod).

This answers ONE question for the whole account: what exists in AWS that git does not
know about, and what did Crossplane create and then lose track of.

── The classification is EXACT, not a heuristic ─────────────────────────────────────
upjet tags every resource it creates, and `crossplane-name` IS the managed resource's
`metadata.name`. Verified 2026-10-01 on a real XBucket-created bucket:

    crossplane-providerconfig: default
    crossplane-kind:           bucket.s3.aws.upbound.io   <- lower(Kind) + "." + apiGroup
    crossplane-name:           models-library-fb95ee084cd7

So (crossplane-kind, crossplane-name) is a primary key into the live managed-resource
set read from the Kubernetes API. No fuzzy matching, no name conventions:

    managed            crossplane tags present AND a live MR of that kind/name exists
    orphaned           crossplane tags present, MR index trustworthy, NO matching MR
                       -> Crossplane made it and lost it. Bills forever. Should be 0.
    unmanaged          no crossplane-* tags -> console/CLI/legacy/packer. Exact without
                       the MR index, because it depends only on the resource's own tags.
    crossplane-tagged  crossplane tags present but the MR index is UNAVAILABLE, so
                       managed-vs-orphaned is UNDECIDABLE. This bucket exists so that a
                       Kubernetes RBAC failure can never be mistaken for "0 orphans".

── Enumeration: Resource Explorer is PRIMARY, the tagging API is the coverage floor ──
AWS Resource Explorer (`resource-explorer-2:Search`) is the primary source because it
is strictly more expansive than `tag:GetResources`: it indexes resources that do not
support tagging at all. On this account a wildcard search in us-west-2 returns 77
resources including `ec2:vpc` and 29 x `ec2:security-group-rule`, which the tagging API
never returns. Its default view already includes tags (IncludedProperties: [{tags}]),
so the exact classification above works straight off Search output — no second call.

But Resource Explorer's coverage here is INCOMPLETE, and this matters more than it
sounds. Verified 2026-10-01 via `list-indexes`:

    us-east-1  LOCAL      us-west-2  LOCAL      (everything else: NO INDEX)

A LOCAL index answers only for its own region, and there is no AGGREGATOR, so there is
no cross-region query. us-east-2 — where the GPU rigs actually run — has no index at
all. Closing that needs two AWS WRITES that are deliberately NOT in this exporter's
IAM policy and must be run by a human (see the IAM note in inventory-ro-user.yaml):

    aws resource-explorer-2 create-index --region us-east-2
    # wait for the index to reach ACTIVE (minutes), then promote ONE region:
    aws resource-explorer-2 update-index-type \
        --arn <us-east-1-index-arn> --type AGGREGATOR --region us-east-1

Until then the Resource Groups Tagging API runs as the SECONDARY source over EVERY
enabled region. It is the only thing that sees us-east-2 today. Every resource carries
a `source` label (resource-explorer / tagging-api / both) so the divergence is visible
rather than assumed, and `aws_inventory_region_unindexed` names each region that
Resource Explorer cannot see.

── Index lag is real and it manufactures false orphans ──────────────────────────────
Both APIs are eventually consistent. Verified 2026-10-01: the us-east-2 tagging API
still returns

    arn:aws:ec2:us-east-2:...:instance/i-07c9140f294b30ed9
      crossplane-kind: instance.ec2.aws.upbound.io
      crossplane-name: gpu-node-27b-fp8-a17c761ce312

while `describe-instances --instance-ids i-07c9140f294b30ed9` returns ZERO reservations
and the region holds no instances at all. There is no live MR of that name either, so a
naive classifier calls that an ORPHAN and the alert stays red forever over a resource
that does not exist and bills nothing.

So every orphan carries a `freshness` label derived from Resource Explorer's
`LastReportedAt`, and the alertable rollup is split by it:

    fresh       Resource Explorer re-confirmed it within ORPHAN_FRESH_MAX_AGE  -> ALERT
    stale       Resource Explorer has not re-confirmed it recently             -> review
    unverified  tagging-API-only row; that API reports no timestamp at all     -> review

── NEVER default a failed scan to zero ──────────────────────────────────────────────
A partial scan reporting no orphans is worse than no scan. Three mechanisms:
  1. The orphan rollups are OMITTED ENTIRELY when the MR index is untrustworthy. The
     series goes absent, so `absent()` fires and a panel reads "No data" — it does not
     read 0. (The old dashboard's `sum(aws_unmanaged_resource) or vector(0)` is exactly
     the bug this guards against.)
  2. Every failure is published with its AWS error code as a LABEL, so AccessDenied is
     visibly different from "nothing found": aws_inventory_scrape_error_info{code=...}.
  3. Nothing is inferred from a region that failed. aws_inventory_region_scanned goes
     to 0 for it and its resources simply are not in the rollups.

── What is NOT available from Resource Explorer ─────────────────────────────────────
Search returns identity (ARN, type, region, tags) but no state, no instance type and no
capacity numbers. Running $/hr, stopped-vs-running, EBS sizes and — importantly — EC2
Fleet fulfilment still require `describe_*`, so a narrower detail sweep stays. A
`maintain` fleet can sit `active` with FulfilledCapacity 0, silently failing to place
while also replacing any instance that vanishes; `terminateInstances: true` makes a
stranded fleet the difference between "deleting the XR stopped the bill" and "it did
not". Fleets and launch templates are therefore described explicitly.

Read-only everywhere: only describe_*/list_*/get_*/Search calls to AWS, only get/list to
Kubernetes. AWS creds come from the scoped read-only IAM user (catalyst-aws-inventory-ro)
via env; Kubernetes creds come from the exporter's ServiceAccount token. Mirrors the
cf-records-exporter shape: a background refresh thread + a stdlib HTTP server serving the
last snapshot, scraped by a PodMonitor. boto3 only (no prometheus_client, no kubernetes).

Local debug: `kubectl proxy --port=18001` then
    K8S_API=http://127.0.0.1:18001 SCRAPE_INTERVAL=99999 python3 exporter.py
"""
import json
import os
import re
import ssl
import threading
import time
import traceback
import urllib.error
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import boto3
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError

# ── config ───────────────────────────────────────────────────────────────────────────
SCRAPE_INTERVAL = int(os.environ.get("SCRAPE_INTERVAL", "600"))  # AWS state is slow-moving
PORT = int(os.environ.get("METRICS_PORT", "9100"))
REGIONS_ENV = os.environ.get("AWS_REGIONS", "").strip()  # restrict via comma-list, else ALL enabled
HOME_REGION = os.environ.get("AWS_HOME_REGION", "us-east-1")  # global clients + list_indexes

RE_ENABLED = os.environ.get("RESOURCE_EXPLORER_ENABLED", "1") == "1"
TAGGING_ENABLED = os.environ.get("TAGGING_API_ENABLED", "1") == "1"
DETAIL_SWEEP = os.environ.get("DETAIL_SWEEP", "1") == "1"

# How recently Resource Explorer must have re-confirmed a resource for an orphan to be
# treated as actionable. At or below this it is `fresh` and alertable; above, `stale`.
ORPHAN_FRESH_MAX_AGE = int(os.environ.get("ORPHAN_FRESH_MAX_AGE_SECONDS", "86400"))

# Per-ARN series are capped so sudden account-wide growth cannot blow up Mimir's
# cardinality. Orphans, undecidables and non-allowlisted unmanaged resources are ALWAYS
# emitted per-ARN regardless of the cap — they are the few that matter — and exceeding
# the cap raises aws_inventory_series_truncated rather than quietly dropping rows.
MAX_RESOURCE_SERIES = int(os.environ.get("MAX_RESOURCE_SERIES", "2000"))

# Kubernetes: in-cluster defaults, overridable for local debugging via `kubectl proxy`.
K8S_API = os.environ.get("K8S_API", "https://kubernetes.default.svc").rstrip("/")
K8S_TOKEN_FILE = os.environ.get("K8S_TOKEN_FILE",
                                "/var/run/secrets/kubernetes.io/serviceaccount/token")
K8S_CA_FILE = os.environ.get("K8S_CA_FILE",
                             "/var/run/secrets/kubernetes.io/serviceaccount/ca.crt")
K8S_TIMEOUT = int(os.environ.get("K8S_TIMEOUT", "20"))

# Unmanaged resources that are NOT drift. Every account has these, most cannot be
# deleted, and none of them bill — so they need an allowlist, not an alarm. They are
# still exported (allowlisted="1" on aws_resource_info); the allowlist only keeps them
# out of aws_unmanaged_resource_count{allowlisted="0"}, which is the reviewable number.
# Grounded in an actual us-west-2 sweep (2026-10-01), not guessed.
# The env override is NEWLINE-separated, never "|"-separated: these patterns contain
# "|" inside their own alternations, so a "|" split shreds them (caught locally
# before this ever ran in-cluster).
DEFAULT_ALLOWLIST = [
    # Default-VPC furniture: VPC, its subnets, route table, NACL, IGW, DHCP option set.
    r"^arn:aws:ec2:[^:]*:\d*:(vpc|subnet|route-table|network-acl|internet-gateway|dhcp-options)/",
    # SG RULES only — the parent security group is still reported, so nothing hides. A
    # leaked SG shows up; its 29 child rules do not drown the table.
    r"^arn:aws:ec2:[^:]*:\d*:security-group-rule/",
    # AWS service-linked roles and AWS-managed policies: created by services, not by us.
    r"^arn:aws:iam::\d*:role/aws-service-role/",
    r"^arn:aws:iam::aws:policy/",
    # Per-service singletons AWS creates on first use and that cannot be removed.
    r"^arn:aws:athena:[^:]*:\d*:(datacatalog/AwsDataCatalog|workgroup/primary)$",
    r"^arn:aws:events:[^:]*:\d*:event-bus/default$",
    r"^arn:aws:xray:[^:]*:\d*:sampling-rule/Default$",
    r"^arn:aws:apprunner:[^:]*:\d*:autoscalingconfiguration/DefaultConfiguration/",
    r"^arn:aws:memorydb:[^:]*:\d*:(parametergroup/default\.|user/default$|acl/open-access$)",
    r"^arn:aws:elasticache:[^:]*:\d*:user:default$",
    # Resource Explorer's own index and view: the observer observing itself.
    r"^arn:aws:resource-explorer-2:",

    # ── AWS-OWNED, CANNOT BE ANYTHING ELSE (audited 2026-10-02) ──
    # The default security group AWS creates with every VPC and refuses to delete. Listed
    # by ARN because the allowlist matches ARNs and an SG's ARN does not carry its name -
    # and a name-blind `security-group/` pattern would hide every leaked SG, which is the
    # one thing this table exists to show. These three are stable for the account's life.
    r"^arn:aws:ec2:us-east-1:\d*:security-group/sg-084608c8aaa410fea$",
    r"^arn:aws:ec2:us-east-2:\d*:security-group/sg-0bfe49a97e54e33ab$",
    r"^arn:aws:ec2:us-west-2:\d*:security-group/sg-a72e8dc0$",
    # AWS-MANAGED KMS keys (KeyManager=AWS), e.g. the default that protects Secrets
    # Manager when no CMK is given. Not creatable or deletable by us.
    r"^arn:aws:kms:[^:]*:\d*:key/eb236f9e-de53-4030-b63d-1926d2775079$",
    # ElastiCache's IAM-auth defaults, alongside the plain `default` user already above.
    r"^arn:aws:elasticache:[^:]*:\d*:user:default\.",
    r"^arn:aws:elasticache:[^:]*:\d*:usergroup:default\.",
    # The free account-level S3 Storage Lens dashboard AWS enables for everyone.
    r"^arn:aws:s3:[^:]*:\d*:storage-lens/default-account-dashboard$",

    # ── ACCOUNT-LEVEL FACTS THAT CANNOT LIVE IN GIT (audited 2026-10-02) ──
    # These are not infrastructure and Crossplane has no business owning them. Leaving
    # them reviewable would mean the review list can never reach zero, which trains
    # everyone to ignore it.
    # How the account pays its bill.
    r"^arn:aws:payments::\d*:payment-instrument:",
    # The human operator's own login and MFA device. A Crossplane-managed IAM user is a
    # service identity; this one is a person, and tagging it would be a lie.
    r"^arn:aws:iam::\d*:mfa/",
    r"^arn:aws:iam::\d*:user/panda$",
    # Cost Explorer anomaly detection: console-created, account-scoped, and WANTED - it is
    # part of how overspend gets noticed. No Crossplane kind exists for it.
    r"^arn:aws:ce::\d*:anomaly(monitor|subscription)/",
]
_ALLOW_ENV = os.environ.get("UNMANAGED_ALLOWLIST", "").strip()
ALLOWLIST_RE = [re.compile(p.strip()) for p in
                (_ALLOW_ENV.splitlines() if _ALLOW_ENV else DEFAULT_ALLOWLIST) if p.strip()]

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

_boto = Config(retries={"max_attempts": 3, "mode": "standard"},
               connect_timeout=10, read_timeout=40)
_snapshot = ("# HELP aws_inventory_scrape_success 1 if the last sweep succeeded.\n"
             "# TYPE aws_inventory_scrape_success gauge\naws_inventory_scrape_success 0\n")
_lock = threading.Lock()

MANAGED, ORPHANED = "managed", "orphaned"
STALE_INDEX = "stale-index"   # tagged, no MR, and CONFIRMED ABSENT in AWS (TALOS-04s3)
UNMANAGED, UNDECIDABLE = "unmanaged", "crossplane-tagged"


def _log(m):
    print(f"[aws-inventory-exporter] {m}", flush=True)


def _esc(v):
    return str(v).replace("\\", "\\\\").replace('"', '\\"').replace("\n", " ")


# ── metric assembly ──────────────────────────────────────────────────────────────────
class Metrics:
    """Collects samples per family so HELP/TYPE is emitted exactly once.

    The previous version wrote HELP/TYPE inline at each call site, which meant adding a
    second emission point for an existing family silently produced a duplicate HELP and
    a text-format parse error. Declaring up front makes that impossible.
    """

    def __init__(self):
        self._fam = {}
        self._order = []

    def declare(self, name, help_, type_="gauge"):
        if name not in self._fam:
            self._fam[name] = {"help": help_, "type": type_, "lines": []}
            self._order.append(name)

    def has(self, name):
        return name in self._fam

    def total(self, name):
        """Sum of the values emitted for a family — used for derived trust gauges."""
        if name not in self._fam:
            return 0.0
        return sum(float(line.rsplit(" ", 1)[1]) for line in self._fam[name]["lines"])

    def add(self, name, labels=None, value=1):
        fam = self._fam[name]  # KeyError here is a bug: declare() first.
        if labels:
            rendered = ",".join(f'{k}="{_esc(v)}"' for k, v in labels.items())
            fam["lines"].append(f"{name}{{{rendered}}} {value}")
        else:
            fam["lines"].append(f"{name} {value}")

    def render(self):
        out = []
        for name in self._order:
            fam = self._fam[name]
            out.append(f"# HELP {name} {fam['help']}")
            out.append(f"# TYPE {name} {fam['type']}")
            out.extend(fam["lines"])
        return "\n".join(out) + "\n"


class Errors:
    """Every failure, keyed by (source, region, op), carrying the AWS/HTTP error CODE.

    The code lands in a metric label specifically so that a permissions failure is
    distinguishable from an empty result at query time, without reading pod logs.
    """

    def __init__(self):
        self.items = {}

    def record(self, source, region, op, exc):
        code = _error_code(exc)
        key = (source, region, op, code)
        self.items[key] = self.items.get(key, 0) + 1
        _log(f"ERROR source={source} region={region} op={op} code={code}: {exc}")

    def __len__(self):
        return sum(self.items.values())


def _error_code(exc):
    if isinstance(exc, ClientError):
        return exc.response.get("Error", {}).get("Code") or "ClientError"
    if isinstance(exc, urllib.error.HTTPError):
        return f"HTTP{exc.code}"
    if isinstance(exc, urllib.error.URLError):
        return "URLError"
    if isinstance(exc, BotoCoreError):
        return type(exc).__name__
    return type(exc).__name__


# ── layer 1: the live managed-resource index, read from the Kubernetes API ───────────
# Kinds are DISCOVERED, never hardcoded. A hardcoded list silently stops covering kinds
# added by a provider upgrade or a newly installed provider family — which is the exact
# drift mechanism this exporter exists to catch, so hardcoding would make the tool lie
# about the one thing it was built to find.
#
# Discovery walks /apis -> each group's preferred version -> the resources carrying
# Crossplane's `managed` category. That category is what `kubectl get managed` uses, and
# every upjet MR CRD advertises it (verified: s3.aws.upbound.io buckets report
# categories ["crossplane","managed","aws"]). Filtering on the CATEGORY rather than on a
# group-name pattern means non-AWS providers are covered for free.
#
# Objects are fetched as PartialObjectMetadataList, so only metadata crosses the wire —
# MR specs are large and nothing here reads them.
#
# ⚠️ The index is keyed on metadata.name ALONE, with no namespace, because that is what
# upjet puts in the crossplane-name tag — adding a namespace to the key would break the
# join outright. The namespaced "m" provider families (s3.aws.m.upbound.io and friends)
# therefore collide if two MRs in different namespaces share a name. That direction of
# error is the safe one: a collision can only make an orphan look MANAGED, never make a
# live managed resource look orphaned, so it cannot manufacture a false alert. It can
# mask a real orphan, so revisit this if namespaced MRs ever come into real use here
# (today the only namespaced managed kind in use is kubernetes.m.crossplane.io Objects,
# which carry no AWS tags at all).
_K8S_META_ACCEPT = "application/json;as=PartialObjectMetadataList;v=v1;g=meta.k8s.io"


def _k8s_ctx():
    token, ctx = None, None
    if os.path.exists(K8S_TOKEN_FILE):
        with open(K8S_TOKEN_FILE, encoding="utf-8") as fh:
            token = fh.read().strip()
    if K8S_API.startswith("https"):
        ctx = ssl.create_default_context(
            cafile=K8S_CA_FILE if os.path.exists(K8S_CA_FILE) else None)
    return token, ctx


def _k8s_get(path, token, ctx, accept="application/json"):
    req = urllib.request.Request(f"{K8S_API}{path}", headers={"Accept": accept})
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    with urllib.request.urlopen(req, timeout=K8S_TIMEOUT, context=ctx) as resp:
        return json.loads(resp.read().decode())


def managed_resource_index(errors):
    """-> (index, ok, kinds_discovered, kinds_listed).

    index maps the upjet `crossplane-kind` tag value -> set of metadata.name.
    ok is False if discovery failed outright or ANY discovered kind could not be listed.
    A single 403 flips ok to False: a partial MR set turns live managed resources into
    phantom orphans, which is worse than reporting nothing.
    """
    index, kinds_discovered, kinds_listed = {}, 0, 0
    token, ctx = _k8s_ctx()
    try:
        groups = _k8s_get("/apis", token, ctx)
    except Exception as exc:  # noqa: BLE001 — recorded, never swallowed
        errors.record("kubernetes", "-", "discover-groups", exc)
        return index, False, 0, 0

    ok = True
    for group in (groups.get("groups") or []):
        gname = group.get("name", "")
        if not gname:
            continue
        # EVERY served version, not just preferredVersion. A CRD that serves only an older
        # version does NOT appear under the group's preferred one, so iterating the
        # preferred version alone made whole MR kinds INVISIBLE - and an invisible kind
        # does not look like an error, it looks like every one of its resources being an
        # orphan. Measured 2026-10-02 on ec2.aws.upbound.io, preferred v1beta2:
        #   launchtemplates  serves v1beta1 + v1beta2 -> found     -> classified managed
        #   fleets           serves v1beta1 only      -> NOT found -> phantom orphan
        #   securitygroups   serves v1beta1 only      -> NOT found -> phantom orphan
        #   volumes          serves v1beta1 only      -> NOT found -> phantom orphan
        # Worse, it was silent: kinds_discovered == kinds_listed, so mr_ok stayed True and
        # the whole orphan rollup was published as authoritative. The
        # MrKindCoverageGap alert compares discovered against listed and so cannot see a
        # kind that was never discovered at all.
        versions = [v.get("version") for v in (group.get("versions") or []) if v.get("version")]
        if not versions:
            pref = (group.get("preferredVersion") or {}).get("version")
            versions = [pref] if pref else []
        seen_kinds = set()
        for version in versions:
            try:
                listing = _k8s_get(f"/apis/{gname}/{version}", token, ctx)
            except Exception as exc:  # noqa: BLE001
                errors.record("kubernetes", "-", f"discover-{gname}/{version}", exc)
                ok = False
                continue
            for res in (listing.get("resources") or []):
                if "/" in res.get("name", ""):
                    continue  # subresource
                if "managed" not in (res.get("categories") or []):
                    continue
                if "list" not in (res.get("verbs") or []):
                    continue
                # upjet's tag value is lower(Kind) + "." + apiGroup, e.g.
                # bucket.s3.aws.upbound.io. Build the same key so the join is exact.
                kind_tag = f"{res['kind'].lower()}.{gname}"
                # The same kind is served by several versions and returns the SAME objects
                # from each, so list it once - via the first (preferred) version that
                # exposes it - and skip the duplicates.
                if kind_tag in seen_kinds:
                    continue
                seen_kinds.add(kind_tag)
                kinds_discovered += 1
                names, listed_ok = _k8s_list_names(gname, version, res["name"], token, ctx, errors)
                if listed_ok:
                    kinds_listed += 1
                    index.setdefault(kind_tag, set()).update(names)
                else:
                    ok = False
    if kinds_discovered == 0:
        ok = False  # discovery "succeeded" but found nothing -> broken, not empty
    return index, ok, kinds_discovered, kinds_listed


def _k8s_list_names(group, version, plural, token, ctx, errors):
    names, cont = [], None
    while True:
        query = {"limit": "500"}
        if cont:
            query["continue"] = cont
        path = f"/apis/{group}/{version}/{plural}?{urllib.parse.urlencode(query)}"
        try:
            page = _k8s_get(path, token, ctx, accept=_K8S_META_ACCEPT)
        except Exception as exc:  # noqa: BLE001
            errors.record("kubernetes", "-", f"list-{plural}.{group}", exc)
            return names, False
        names.extend(item["metadata"]["name"] for item in (page.get("items") or []))
        cont = (page.get("metadata") or {}).get("continue")
        if not cont:
            return names, True


# ── ARN helpers ──────────────────────────────────────────────────────────────────────
# Resource Explorer hands back Service and ResourceType directly. The tagging API hands
# back only an ARN, so these derive the same two fields from it. Deliberately small and
# honest: Resource Explorer's values win whenever both sources saw a resource.
_S3_LIKE = {"s3": "bucket"}


def _arn_parts(arn):
    bits = arn.split(":", 5)
    if len(bits) < 6:
        return "", "", ""
    _, _, service, region, _, resource = bits
    if "/" in resource:
        rtype = resource.split("/", 1)[0]
    elif ":" in resource:
        rtype = resource.split(":", 1)[0]
    else:
        rtype = _S3_LIKE.get(service, service)
    return service, region, rtype


# ── layer 2: AWS Resource Explorer (PRIMARY) ────────────────────────────────────────
def resource_explorer_indexes(errors):
    """-> (region -> index type, ok). ONE account-level call; any region's endpoint answers.

    `ok` matters: if this call fails we do not know which regions are indexed, and
    publishing "every region is unindexed" would invent a blind spot that may not exist.
    """
    try:
        client = boto3.client("resource-explorer-2", region_name=HOME_REGION, config=_boto)
        found = {}
        for page in client.get_paginator("list_indexes").paginate():
            for idx in (page.get("Indexes") or []):
                found[idx["Region"]] = idx.get("Type", "UNKNOWN")
        return found, True
    except Exception as exc:  # noqa: BLE001
        errors.record("resource-explorer", HOME_REGION, "list-indexes", exc)
        return {}, False


def resource_explorer_search(region, errors):
    """-> (rows, complete, ok). Wildcard search against the region's DEFAULT view.

    The default view already carries IncludedProperties [{tags}], so one call returns
    identity AND tags — no per-resource tag lookup. `complete` is AWS's own
    Count.Complete: when it is False the result set is truncated and must not be treated
    as authoritative, so it is exported rather than discarded.
    """
    rows, complete = [], True
    try:
        client = boto3.client("resource-explorer-2", region_name=region, config=_boto)
        for page in client.get_paginator("search").paginate(QueryString="*"):
            complete = complete and bool((page.get("Count") or {}).get("Complete", True))
            for res in (page.get("Resources") or []):
                tags, reported = {}, None
                for prop in res.get("Properties") or []:
                    if prop.get("Name") == "tags":
                        tags = {t["Key"]: t["Value"] for t in prop.get("Data") or []}
                last = res.get("LastReportedAt")
                if last is not None:
                    reported = last.timestamp()
                rows.append({
                    "arn": res["Arn"],
                    "service": res.get("Service") or _arn_parts(res["Arn"])[0],
                    "type": res.get("ResourceType") or "",
                    "region": res.get("Region") or region,
                    "tags": tags,
                    "last_reported": reported,
                    "source": "resource-explorer",
                })
        return rows, complete, True
    except Exception as exc:  # noqa: BLE001
        errors.record("resource-explorer", region, "search", exc)
        return [], False, False


# ── layer 3: Resource Groups Tagging API (SECONDARY / coverage floor) ───────────────
def tagging_api_scan(region, errors):
    """-> (rows, ok). One paginated call per region, every taggable service, no
    per-service code. Only sees TAGGED resources, and reports no freshness timestamp —
    hence `unverified` rather than `fresh`. Today it is the ONLY source covering any
    region without a Resource Explorer index, us-east-2 included.
    """
    rows = []
    try:
        client = boto3.client("resourcegroupstaggingapi", region_name=region, config=_boto)
        for page in client.get_paginator("get_resources").paginate():
            for res in (page.get("ResourceTagMappingList") or []):
                arn = res["ResourceARN"]
                service, arn_region, rtype = _arn_parts(arn)
                rows.append({
                    "arn": arn,
                    "service": service,
                    "type": f"{service}:{rtype}" if service else rtype,
                    "region": arn_region or region,
                    "tags": {t["Key"]: t["Value"] for t in res.get("Tags") or []},
                    "last_reported": None,
                    "source": "tagging-api",
                })
        return rows, True
    except Exception as exc:  # noqa: BLE001
        errors.record("tagging-api", region, "get-resources", exc)
        return [], False


# ── tag enrichment: types the inventory APIs return WITHOUT tags ────────────────────
# Neither inventory API gives us tags for every type, and a row with no tags classifies
# as "unmanaged" — which is an assertion that git does not know about the resource. For
# a type whose tags we simply could not read, that assertion is false.
#
# Measured on this account 2026-10-01:
#   iam:policy, iam:instance-profile  tagging API returns them WITH crossplane tags  -> classified correctly
#   iam:role, iam:user                Resource Explorer indexes them but returns an
#                                     EMPTY Properties array, and the tagging API does
#                                     not return them at all -> every one of them was
#                                     being reported as unmanaged, including
#                                     catalyst-gpu-seeder and catalyst-ssm, which carry
#                                     correct crossplane-kind/crossplane-name tags.
#
# That is a FALSE UNMANAGED, which is the dangerous direction twice over: it puts
# git-managed identities in the human review pile, and it makes an orphaned IAM role
# undetectable, because a row with no tags can never reach the orphan branch.
#
# So for these types we go and read the tags from the owning service. N is small (the
# inventory already bounds it to resources that exist) and it only fires on rows that
# arrived with no crossplane tag at all, so a correctly-tagged row costs nothing.
#
# Needs iam:ListRoleTags + iam:ListUserTags, both reads, both added to
# infrastructure/base/aws/inventory-ro-user.yaml.
TAG_BLIND_TYPES = {
    "iam:role": ("iam", "list_role_tags", "RoleName"),
    "iam:user": ("iam", "list_user_tags", "UserName"),
}


def enrich_tags(merged, errors):
    """Fill in tags for TAG_BLIND_TYPES rows. -> (enriched_count, all_ok).

    all_ok=False feeds the authoritative gate: if we could not read the tags, a zero
    orphan count is not something we are entitled to publish.
    """
    targets = [(arn, row) for arn, row in merged.items()
               if row["type"] in TAG_BLIND_TYPES
               and not any(k.startswith("crossplane-") for k in row["tags"])]
    if not targets:
        return 0, True
    clients, enriched, all_ok = {}, 0, True
    for arn, row in targets:
        service, op, param = TAG_BLIND_TYPES[row["type"]]
        try:
            if service not in clients:
                clients[service] = boto3.client(service, config=_boto)
            # ARN tail is the resource name; IAM paths mean it can contain slashes.
            resp = getattr(clients[service], op)(**{param: arn.split("/")[-1]})
            tags = {t["Key"]: t["Value"] for t in resp.get("Tags", [])}
            if tags:
                row["tags"].update(tags)
                enriched += 1
        except Exception as exc:  # noqa: BLE001
            errors.record(service, row["region"], f"{op}:{row['type']}", exc)
            all_ok = False
    return enriched, all_ok


# ── existence verification (TALOS-04s3) ──────────────────────────────────────────────
# BOTH inventory APIs keep returning resources after deletion. A deleted resource looks
# EXACTLY like an orphan - crossplane tags present, no live MR - so without this check
# every teardown manufactures phantom orphans. Measured 2026-10-02: four fleets reported
# orphaned, three of which did not exist at all and one of which was state=deleted.
#
# freshness does NOT substitute for this. It comes from LastReportedAt, which says the
# INDEX touched the row recently, not that the resource exists; three of those four
# phantoms were in the `fresh` tier.
#
# Cost is bounded by the ORPHAN CANDIDATE count - normally zero - not by inventory size,
# which is why a per-resource API call is affordable here and nowhere else in this file.
#
# (service, method, id-kwarg, absent-marker-substrings). The markers are matched against
# the botocore error code, so a permissions failure is NOT mistaken for absence.
EXISTENCE_CHECKS = {
    "ec2:fleet":           ("ec2", "describe_fleets", "FleetIds", ("InvalidFleetId.NotFound",)),
    "ec2:instance":        ("ec2", "describe_instances", "InstanceIds", ("InvalidInstanceID.NotFound",)),
    "ec2:security-group":  ("ec2", "describe_security_groups", "GroupIds", ("InvalidGroup.NotFound",)),
    "ec2:launch-template": ("ec2", "describe_launch_templates", "LaunchTemplateIds", ("InvalidLaunchTemplateId.NotFound",)),
    "ec2:volume":          ("ec2", "describe_volumes", "VolumeIds", ("InvalidVolume.NotFound",)),
    "iam:role":            ("iam", "get_role", "RoleName", ("NoSuchEntity",)),
    "iam:user":            ("iam", "get_user", "UserName", ("NoSuchEntity",)),
    "iam:policy":          ("iam", "get_policy", "PolicyArn", ("NoSuchEntity",)),
    "s3:bucket":           ("s3", "head_bucket", "Bucket", ("404", "NoSuchBucket")),
}
# An EC2 instance can exist and still be gone. terminated/shutting-down instances keep
# answering describe for ~an hour, so the API returning one is not evidence of existence.
_DEAD_INSTANCE_STATES = ("terminated", "shutting-down")


def verify_existence(candidates, errors):
    """Which orphan candidates are confirmed GONE? -> (absent_arns, all_ok).

    all_ok=False whenever a candidate's existence could not be established - either no
    check is mapped for its type, or the call failed. That feeds the authoritative gate
    for the same reason a failed tag read does: an orphan count we cannot substantiate is
    not a number to publish as fact.
    """
    if not candidates:
        return set(), True
    clients, absent, all_ok = {}, set(), True
    for arn, row in candidates:
        check = EXISTENCE_CHECKS.get(row["type"])
        if check is None:
            errors.record("existence", row["region"], f"unmapped:{row['type']}",
                          Exception("no existence check for this type"))
            all_ok = False
            continue
        service, op, kwarg, markers = check
        ident = arn.split("/")[-1] if "/" in arn else arn.split(":")[-1]
        key = (service, row["region"])
        try:
            if key not in clients:
                clients[key] = boto3.client(
                    service, config=_boto,
                    **({} if service == "iam" else {"region_name": row["region"]}))
            cli = clients[key]
            arg = arn if row["type"] == "iam:policy" else ident
            resp = getattr(cli, op)(**{kwarg: ([arg] if kwarg.endswith("Ids") else arg)})
            if row["type"] == "ec2:instance":
                states = [i.get("State", {}).get("Name")
                          for r in resp.get("Reservations", []) for i in r.get("Instances", [])]
                # NO states means AWS has aged the record out entirely - that is absent,
                # not "exists". Measured: a long-terminated instance returns an empty
                # Reservations list rather than raising InvalidInstanceID.NotFound, so
                # requiring a non-empty list here reported a dead box as still present.
                if not states or all(st in _DEAD_INSTANCE_STATES for st in states):
                    absent.add(arn)
            elif row["type"] == "ec2:fleet":
                # describe_fleets does NOT 404 a deleted fleet; it returns it as deleted.
                states = [f.get("FleetState") for f in resp.get("Fleets", [])]
                if not states or all(st and st.startswith("deleted") for st in states):
                    absent.add(arn)
        except Exception as exc:  # noqa: BLE001
            resp = getattr(exc, "response", None) or {}
            code = (resp.get("Error") or {}).get("Code") or type(exc).__name__
            if any(mark in code for mark in markers):
                absent.add(arn)          # confirmed gone: a stale index row, not an orphan
            else:
                errors.record(service, row["region"], f"{op}:{row['type']}", exc)
                all_ok = False
    return absent, all_ok


# ── classification ───────────────────────────────────────────────────────────────────
def classify(tags, mr_index, mr_ok):
    """-> (management, crossplane_kind, crossplane_name)."""
    kind = tags.get("crossplane-kind", "")
    name = tags.get("crossplane-name", "")
    if not kind and not name:
        # Exact without Kubernetes: depends only on the resource's own tags.
        return UNMANAGED, "", ""
    if not mr_ok:
        # Tagged by Crossplane, but we cannot see the live MR set. Saying "managed"
        # would hide orphans; saying "orphaned" would cry wolf. Say neither.
        return UNDECIDABLE, kind, name
    return (MANAGED if name in mr_index.get(kind, ()) else ORPHANED), kind, name


def allowlisted(arn):
    return any(pattern.search(arn) for pattern in ALLOWLIST_RE)


def freshness(row):
    if row["last_reported"] is None:
        return "unverified"  # tagging-API-only: that API publishes no timestamp
    return "fresh" if (time.time() - row["last_reported"]) <= ORPHAN_FRESH_MAX_AGE else "stale"


def _regions(errors):
    if REGIONS_ENV:
        return [r.strip() for r in REGIONS_ENV.split(",") if r.strip()], True
    try:
        ec2 = boto3.client("ec2", region_name=HOME_REGION, config=_boto)
        resp = ec2.describe_regions(Filters=[{"Name": "opt-in-status",
                                              "Values": ["opt-in-not-required", "opted-in"]}])
        return sorted(r["RegionName"] for r in resp["Regions"]), True
    except Exception as exc:  # noqa: BLE001
        errors.record("ec2", HOME_REGION, "describe-regions", exc)
        return [], False


# ── the inventory sweep ──────────────────────────────────────────────────────────────
def inventory(m, errors, mr_index, mr_ok, regions):
    """Merge Resource Explorer + tagging API by ARN, classify, emit.

    -> (merged, complete_all, scanned_regions, aggregator_present)
    """
    m.declare("aws_inventory_resource_explorer_index",
              "A Resource Explorer index (value=1); type label is LOCAL or AGGREGATOR.")
    m.declare("aws_inventory_resource_explorer_aggregator",
              "1 if an AGGREGATOR index exists (cross-region query possible), else 0.")
    m.declare("aws_inventory_region_unindexed",
              "1 for an enabled region with NO Resource Explorer index — a blind spot "
              "the tagging API only partly covers (tagged resources only).")
    m.declare("aws_inventory_region_scanned",
              "1 if this region was scanned successfully by this source, 0 if it failed.")
    m.declare("aws_inventory_region_search_complete",
              "Resource Explorer Count.Complete for this region; 0 = truncated result set.")
    m.declare("aws_inventory_source_resources",
              "Resources returned by one source in one region (RE vs tagging divergence).")

    err_before = len(errors)
    re_indexes, re_list_ok = resource_explorer_indexes(errors) if RE_ENABLED else ({}, True)
    aggregator = any(t == "AGGREGATOR" for t in re_indexes.values())
    for region, itype in sorted(re_indexes.items()):
        m.add("aws_inventory_resource_explorer_index", {"region": region, "type": itype})
    m.add("aws_inventory_resource_explorer_aggregator", None, 1 if aggregator else 0)
    if re_list_ok:
        for region in regions:
            if region not in re_indexes:
                m.add("aws_inventory_region_unindexed", {"region": region})

    merged, complete_all, scanned = {}, True, set()

    def absorb(rows, source, region):
        m.add("aws_inventory_source_resources", {"source": source, "region": region}, len(rows))
        for row in rows:
            existing = merged.get(row["arn"])
            if existing is None:
                merged[row["arn"]] = row
                continue
            # Resource Explorer wins on identity (authoritative Service/ResourceType and
            # the only source with a timestamp); tags are unioned so a tag visible to
            # only one source still classifies.
            if existing["source"] != row["source"]:
                existing["source"] = "both"
            if row["last_reported"] is not None and existing["last_reported"] is None:
                existing["last_reported"] = row["last_reported"]
            for key, value in row["tags"].items():
                existing["tags"].setdefault(key, value)

    # PRIMARY: Resource Explorer, per region, against that region's own LOCAL index.
    # Once an AGGREGATOR exists this collapses to a single search from its region.
    if RE_ENABLED:
        for region in sorted(re_indexes):
            if regions and region not in regions:
                continue
            rows, complete, ok = resource_explorer_search(region, errors)
            m.add("aws_inventory_region_scanned",
                  {"region": region, "source": "resource-explorer"}, 1 if ok else 0)
            m.add("aws_inventory_region_search_complete", {"region": region},
                  1 if complete else 0)
            complete_all = complete_all and complete
            if ok:
                scanned.add(region)
                absorb(rows, "resource-explorer", region)

    # SECONDARY: the tagging API everywhere, because Resource Explorer sees 2 of 17
    # regions today. Drop to Resource-Explorer-only by setting TAGGING_API_ENABLED=0
    # AFTER an AGGREGATOR index exists — not before.
    if TAGGING_ENABLED:
        for region in regions:
            rows, ok = tagging_api_scan(region, errors)
            m.add("aws_inventory_region_scanned",
                  {"region": region, "source": "tagging-api"}, 1 if ok else 0)
            if ok:
                scanned.add(region)
                absorb(rows, "tagging-api", region)

    # ── classify + emit ─────────────────────────────────────────────────────────────
    m.declare("aws_resource_info",
              "One AWS resource (value=1). management is managed/orphaned/unmanaged, or "
              "crossplane-tagged when the live MR set could not be read.")
    m.declare("aws_resource_last_reported_timestamp_seconds",
              "Unix time Resource Explorer last re-confirmed this resource. Absent for "
              "tagging-API-only rows, which carry no timestamp.")
    m.declare("aws_resource_count", "Resource count by service/type/region/management.")
    m.declare("aws_orphaned_resource",
              "Crossplane created it and lost it: crossplane tags present, NO live "
              "managed resource. Bills forever. OMITTED when the MR index is unreadable.")
    m.declare("aws_unmanaged_resource",
              "A live resource with NO crossplane tag (console/CLI/legacy). "
              "allowlisted=1 marks the AWS defaults that are expected to be unmanaged.")
    m.declare("aws_inventory_resources_total", "Distinct ARNs in the merged inventory.")
    m.declare("aws_inventory_series_truncated",
              "1 if MAX_RESOURCE_SERIES capped the per-ARN aws_resource_info series. "
              "Rollups, orphans and non-allowlisted unmanaged rows are never capped.")

    rollup, orphan_rollup, unmanaged_rollup = {}, {}, {}
    emitted, truncated = 0, False
    # Read tags the inventory APIs withheld, BEFORE classifying — otherwise a
    # git-managed IAM role is reported as unmanaged. See TAG_BLIND_TYPES.
    matched_pairs = set()
    enriched, tags_ok = enrich_tags(merged, errors)
    m.declare("aws_inventory_tag_enrichment",
              "Rows whose tags the inventory APIs omitted and we fetched from the "
              "owning service (see TAG_BLIND_TYPES). complete=0 means some could not "
              "be read, so classification for those types is not trustworthy.")
    m.add("aws_inventory_tag_enrichment", {"result": "enriched"}, enriched)
    m.add("aws_inventory_tag_enrichment", {"result": "complete"}, 1 if tags_ok else 0)

    # Then ask AWS whether each orphan candidate still EXISTS (TALOS-04s3). Both inventory
    # APIs keep returning deleted resources, and a deleted resource is indistinguishable
    # from an orphan by tags alone, so without this every teardown invents orphans.
    # Classification is cheap and pure, so running it twice to find the candidates costs
    # nothing and keeps the expensive call off every other row.
    candidates = [(a, r) for a, r in merged.items()
                  if classify(r["tags"], mr_index, mr_ok)[0] == ORPHANED]
    absent, exists_ok = verify_existence(candidates, errors)
    m.declare("aws_inventory_stale_index_rows",
              "Orphan candidates that AWS confirms are GONE: the inventory API is serving "
              "a deleted resource. Informational, never alertable — but worth seeing, "
              "because it explains away a number someone would otherwise chase.")
    m.add("aws_inventory_stale_index_rows", None, len(absent))
    m.declare("aws_inventory_existence_checks",
              "Orphan candidates whose existence was checked, and whether every check "
              "succeeded. complete=0 means an orphan count cannot be substantiated.")
    m.add("aws_inventory_existence_checks", {"result": "checked"}, len(candidates))
    m.add("aws_inventory_existence_checks", {"result": "complete"}, 1 if exists_ok else 0)

    for arn in sorted(merged):
        row = merged[arn]
        management, kind, name = classify(row["tags"], mr_index, mr_ok)
        if management == ORPHANED and arn in absent:
            # Tagged, no MR — but AWS says it is gone. That is a stale index row, not an
            # orphan, and calling it an orphan is how the alert gets muted.
            management = STALE_INDEX
        allow = allowlisted(arn)
        always = (management in (ORPHANED, UNDECIDABLE)
                  or (management == UNMANAGED and not allow))
        if emitted < MAX_RESOURCE_SERIES or always:
            m.add("aws_resource_info", {
                "arn": arn, "service": row["service"], "type": row["type"],
                "region": row["region"], "management": management,
                "crossplane_kind": kind, "crossplane_name": name,
                "source": row["source"], "allowlisted": "1" if allow else "0"})
            if row["last_reported"] is not None:
                m.add("aws_resource_last_reported_timestamp_seconds", {"arn": arn},
                      int(row["last_reported"]))
            emitted += 1
        else:
            truncated = True

        if management == MANAGED:
            matched_pairs.add((kind, name))
        key = (row["service"], row["type"], row["region"], management)
        rollup[key] = rollup.get(key, 0) + 1
        if management == ORPHANED:
            fresh = freshness(row)
            m.add("aws_orphaned_resource", {
                "arn": arn, "service": row["service"], "type": row["type"],
                "region": row["region"], "crossplane_kind": kind,
                "crossplane_name": name, "source": row["source"], "freshness": fresh})
            okey = (row["service"], fresh)
            orphan_rollup[okey] = orphan_rollup.get(okey, 0) + 1
        elif management == UNMANAGED:
            m.add("aws_unmanaged_resource", {
                "arn": arn, "service": row["service"], "type": row["type"],
                "region": row["region"], "name": row["tags"].get("Name", ""),
                "allowlisted": "1" if allow else "0"})
            akey = (row["service"], "1" if allow else "0")
            unmanaged_rollup[akey] = unmanaged_rollup.get(akey, 0) + 1

    # ── what drift detection is BLIND to ────────────────────────────────────────────
    # An MR exists in the cluster but nothing in the merged inventory carries its
    # crossplane-name. Three different reasons, and the distinction matters:
    #   * the resource is a CONFIGURATION SUB-RESOURCE with no ARN or tags of its own
    #     (BucketVersioning, BucketPublicAccessBlock, RolePolicyAttachment, AccessKey) —
    #     expected and permanent, nothing to fix
    #   * NO inventory API indexes the type at all (measured: ecs:service returns 0 from
    #     both Resource Explorer and the tagging API) — a genuine blind spot: an orphan
    #     of that type could never be detected
    #   * the MR never created anything (no status.atProvider.id), so there is correctly
    #     nothing to find
    # Informational, never alertable — most entries are the first case. It exists so the
    # blind spots are COUNTABLE instead of being discovered by accident.
    m.declare("aws_inventory_mr_unmatched",
              "Managed resources with no matching inventory row, by kind. Expected for "
              "non-taggable sub-resources; for a taggable type it means orphans of that "
              "type are undetectable.")
    matched_names = {(k, n) for (k, n) in matched_pairs}
    unmatched = {}
    for kind, names in mr_index.items():
        for name in names:
            if (kind, name) not in matched_names:
                unmatched[kind] = unmatched.get(kind, 0) + 1
    for kind, count in sorted(unmatched.items()):
        m.add("aws_inventory_mr_unmatched", {"crossplane_kind": kind}, count)

    for (service, rtype, region, management), count in sorted(rollup.items()):
        m.add("aws_resource_count", {"service": service, "type": rtype,
                                     "region": region, "management": management}, count)
    m.add("aws_inventory_resources_total", None, len(merged))
    m.add("aws_inventory_series_truncated", None, 1 if truncated else 0)

    m.declare("aws_unmanaged_resource_count",
              "Unmanaged resource count by service; allowlisted=0 is the reviewable number.")
    for (service, allow), count in sorted(unmanaged_rollup.items()):
        m.add("aws_unmanaged_resource_count", {"service": service, "allowlisted": allow}, count)

    # THE number this whole exporter exists for — and the one that must never be a
    # defaulted zero. Two different conditions, deliberately not conflated:
    #
    #   mr_ok          enough to BELIEVE an orphan we found. A crossplane-tagged resource
    #                  with no live MR is a real orphan no matter how patchy the sweep was.
    #   authoritative  enough to BELIEVE A ZERO. Requires the MR index AND a clean sweep
    #                  of every enabled region with no truncation — otherwise the orphan
    #                  could be sitting in whatever we failed to look at.
    #
    # Publishing a 0 off a failed AWS scan was a real bug here, caught by running the
    # exporter with rejected credentials: Kubernetes answered, AWS returned nothing, and
    # "0 orphans" went out over an inventory of zero resources. Absence is the only
    # honest answer in that state, so the whole family is withheld.
    inventory_clean = (len(errors) == err_before and bool(scanned) and complete_all
                       and all(r in scanned for r in regions))
    # tags_ok matters as much as mr_ok: a type whose tags we could not read can never
    # reach the orphan branch, so a zero would be a lower bound presented as a fact.
    # exists_ok belongs here for the same reason tags_ok does: if a candidate's existence
    # could not be established — no check mapped for its type, or the call failed — then a
    # zero orphan count is a lower bound being presented as a fact.
    authoritative = mr_ok and inventory_clean and tags_ok and exists_ok
    m.declare("aws_inventory_orphan_detection_authoritative",
              "1 if a ZERO orphan count can be believed: MR index read in full AND every "
              "enabled region swept cleanly with no truncation. 0 means the orphan count "
              "is a lower bound at best, and the count family is withheld entirely.")
    m.add("aws_inventory_orphan_detection_authoritative", None, 1 if authoritative else 0)
    if mr_ok and (orphan_rollup or authoritative):
        m.declare("aws_orphaned_resource_count",
                  "Orphaned resources by service. freshness=fresh is the alertable one; "
                  "stale/unverified are index-lag suspects needing confirmation.")
        for (service, fresh), count in sorted(orphan_rollup.items()):
            m.add("aws_orphaned_resource_count", {"service": service, "freshness": fresh}, count)
        if not orphan_rollup:
            # An explicit, EARNED zero: the MR index was readable, every region was swept
            # cleanly, and nothing came back orphaned.
            m.add("aws_orphaned_resource_count", {"service": "none", "freshness": "fresh"}, 0)

    return merged, complete_all, scanned, aggregator


# ── layer 4: shape / state / capacity detail (describe_*) ───────────────────────────
# Resource Explorer gives identity, not state. $/hr needs the instance type AND whether
# it is running; fleet health needs TargetCapacity vs FulfilledCapacity. Neither is in
# any tag-based API, so this narrower sweep stays.
def detail_sweep(m, errors, mr_index, mr_ok, regions):
    m.declare("aws_ec2_instance_info",
              "An EC2 instance (value=1); state label includes stopped.")
    m.declare("aws_ebs_volume_size_gb", "An EBS volume; value = size GiB.")
    m.declare("aws_ebs_snapshot_size_gb", "A self-owned EBS snapshot; value = size GiB.")
    m.declare("aws_security_group_info", "A security group (value=1).")
    m.declare("aws_eip_info", "An Elastic IP (value=1); associated label.")
    m.declare("aws_ec2_fleet_info",
              "An EC2 Fleet (value=1). activity_status=error or pending_fulfillment on an "
              "active maintain fleet means it is failing to place instances.")
    m.declare("aws_ec2_fleet_capacity",
              "EC2 Fleet capacity units. kind=target vs kind=fulfilled: target>0 with "
              "fulfilled=0 is a fleet burning nothing and silently placing nothing.")
    m.declare("aws_ec2_launch_template_info",
              "An EC2 LaunchTemplate (value=1); default/latest version numbers in labels.")
    m.declare("aws_ec2_instances", "Instance count by region/type/state.")
    m.declare("aws_ebs_volumes", "EBS volume count by region/state.")
    m.declare("aws_detail_resource_count",
              "Describe-sourced count by kind (incl. things that are off but present).")
    m.declare("aws_estimated_cost_usd_per_hour",
              "Estimated ON-DEMAND $/hr of RUNNING instances.")
    m.declare("aws_estimated_storage_cost_usd_per_month",
              "Idle/standing spend: EBS + snapshots + S3 + unassociated EIPs.")
    m.declare("aws_s3_bucket_info", "An S3 bucket (value=1).")
    m.declare("aws_s3_bucket_bytes", "S3 bucket size in bytes (CloudWatch daily).")
    m.declare("aws_s3_bucket_objects", "S3 bucket object count (CloudWatch daily).")
    m.declare("aws_iam_user_info", "An IAM user (value=1).")
    m.declare("aws_iam_role_info", "A customer IAM role (service-linked excluded) (value=1).")
    m.declare("aws_iam_policy_info", "A customer-managed IAM policy (value=1).")
    m.declare("aws_iam_instance_profile_info", "An IAM instance profile (value=1).")

    ec2_count, ebs_count, cost_hr = {}, {}, {}
    storage_gb = {"ebs": 0.0, "snapshot": 0.0, "s3": 0.0}
    counts = {"sg": 0, "snapshot": 0, "eip": 0, "fleet": 0, "launch_template": 0}
    eip_unassoc = 0

    def mgmt(tags):
        return classify(tags, mr_index, mr_ok)[0]

    def tagmap(taglist):
        return {t["Key"]: t["Value"] for t in (taglist or [])}

    for region in regions:
        ec2 = boto3.client("ec2", region_name=region, config=_boto)
        try:
            for page in ec2.get_paginator("describe_instances").paginate():
                for res in page["Reservations"]:
                    for inst in res["Instances"]:
                        state = inst["State"]["Name"]
                        if state in ("terminated", "shutting-down"):
                            continue
                        tags = tagmap(inst.get("Tags"))
                        itype = inst["InstanceType"]
                        life = "spot" if inst.get("InstanceLifecycle") == "spot" else "on-demand"
                        m.add("aws_ec2_instance_info", {
                            "id": inst["InstanceId"], "region": region, "type": itype,
                            "state": state, "name": tags.get("Name", ""),
                            "lifecycle": life, "management": mgmt(tags)})
                        ckey = (region, itype, state)
                        ec2_count[ckey] = ec2_count.get(ckey, 0) + 1
                        if state == "running":
                            cost_hr[region] = cost_hr.get(region, 0.0) + PRICE.get(itype, 0.0)
        except Exception as exc:  # noqa: BLE001
            errors.record("ec2", region, "describe-instances", exc)

        try:
            for page in ec2.get_paginator("describe_volumes").paginate():
                for vol in page["Volumes"]:
                    m.add("aws_ebs_volume_size_gb", {
                        "id": vol["VolumeId"], "region": region, "state": vol["State"],
                        "management": mgmt(tagmap(vol.get("Tags")))}, vol["Size"])
                    vkey = (region, vol["State"])
                    ebs_count[vkey] = ebs_count.get(vkey, 0) + 1
                    storage_gb["ebs"] += vol["Size"]
        except Exception as exc:  # noqa: BLE001
            errors.record("ec2", region, "describe-volumes", exc)

        try:
            for page in ec2.get_paginator("describe_snapshots").paginate(OwnerIds=["self"]):
                for snap in page["Snapshots"]:
                    size = snap.get("VolumeSize", 0)
                    m.add("aws_ebs_snapshot_size_gb", {
                        "id": snap["SnapshotId"], "region": region,
                        "management": mgmt(tagmap(snap.get("Tags")))}, size)
                    counts["snapshot"] += 1
                    storage_gb["snapshot"] += size
        except Exception as exc:  # noqa: BLE001
            errors.record("ec2", region, "describe-snapshots", exc)

        try:
            for page in ec2.get_paginator("describe_security_groups").paginate():
                for sg in page["SecurityGroups"]:
                    m.add("aws_security_group_info", {
                        "id": sg["GroupId"], "region": region, "name": sg["GroupName"],
                        "vpc": sg.get("VpcId", ""),
                        "management": mgmt(tagmap(sg.get("Tags")))})
                    counts["sg"] += 1
        except Exception as exc:  # noqa: BLE001
            errors.record("ec2", region, "describe-security-groups", exc)

        try:
            for eip in (ec2.describe_addresses().get("Addresses") or []):
                assoc = "1" if eip.get("AssociationId") else "0"
                m.add("aws_eip_info", {
                    "region": region, "public_ip": eip.get("PublicIp", ""),
                    "associated": assoc,
                    "management": mgmt(tagmap(eip.get("Tags")))})
                counts["eip"] += 1
                eip_unassoc += assoc == "0"
        except Exception as exc:  # noqa: BLE001
            errors.record("ec2", region, "describe-addresses", exc)

        # EC2 Fleets (TALOS-i91u replaced the bare Instance with LaunchTemplate + Fleet).
        # `deleted` fleets are dropped, but deleted_running / deleted_terminating are KEPT:
        # those still own instances, so they are still billing.
        try:
            for page in ec2.get_paginator("describe_fleets").paginate():
                for fleet in (page.get("Fleets") or []):
                    state = fleet.get("FleetState", "")
                    if state == "deleted":
                        continue
                    spec = fleet.get("TargetCapacitySpecification") or {}
                    base = {"id": fleet.get("FleetId", ""), "region": region}
                    m.add("aws_ec2_fleet_info", dict(base, **{
                        "state": state,
                        "activity_status": fleet.get("ActivityStatus", ""),
                        "fleet_type": fleet.get("Type", ""),
                        "default_capacity_type": spec.get("DefaultTargetCapacityType", ""),
                        "terminate_instances": str(
                            fleet.get("TerminateInstancesWithExpiration", "")).lower(),
                        "management": mgmt(tagmap(fleet.get("Tags")))}))
                    for kind, value in (
                            ("target", spec.get("TotalTargetCapacity", 0)),
                            ("target_on_demand", spec.get("OnDemandTargetCapacity", 0)),
                            ("target_spot", spec.get("SpotTargetCapacity", 0)),
                            ("fulfilled", fleet.get("FulfilledCapacity", 0)),
                            ("fulfilled_on_demand", fleet.get("FulfilledOnDemandCapacity", 0))):
                        m.add("aws_ec2_fleet_capacity", dict(base, kind=kind), value or 0)
                    counts["fleet"] += 1
        except Exception as exc:  # noqa: BLE001
            errors.record("ec2", region, "describe-fleets", exc)

        try:
            for page in ec2.get_paginator("describe_launch_templates").paginate():
                for tpl in (page.get("LaunchTemplates") or []):
                    m.add("aws_ec2_launch_template_info", {
                        "id": tpl.get("LaunchTemplateId", ""),
                        "name": tpl.get("LaunchTemplateName", ""), "region": region,
                        "default_version": str(tpl.get("DefaultVersionNumber", "")),
                        "latest_version": str(tpl.get("LatestVersionNumber", "")),
                        "management": mgmt(tagmap(tpl.get("Tags")))})
                    counts["launch_template"] += 1
        except Exception as exc:  # noqa: BLE001
            errors.record("ec2", region, "describe-launch-templates", exc)

    # ── global: S3 sizes + IAM ──────────────────────────────────────────────────────
    try:
        s3 = boto3.client("s3", config=_boto)
        for bucket in (s3.list_buckets().get("Buckets") or []):
            name = bucket["Name"]
            try:
                loc = s3.get_bucket_location(Bucket=name).get("LocationConstraint") or "us-east-1"
            except Exception as exc:  # noqa: BLE001 — a denied bucket is still a bucket
                errors.record("s3", "-", "get-bucket-location", exc)
                loc = "unknown"
            m.add("aws_s3_bucket_info", {"name": name, "region": loc})
            size, objects = _s3_size(name, loc, errors)
            m.add("aws_s3_bucket_bytes", {"name": name}, int(size))
            m.add("aws_s3_bucket_objects", {"name": name}, int(objects))
            storage_gb["s3"] += size / (1024 ** 3)
    except Exception as exc:  # noqa: BLE001
        errors.record("s3", "-", "list-buckets", exc)

    try:
        iam = boto3.client("iam", config=_boto)
        for page in iam.get_paginator("list_users").paginate():
            for user in page["Users"]:
                m.add("aws_iam_user_info", {"name": user["UserName"],
                                            "path": user.get("Path", "/")})
        for page in iam.get_paginator("list_roles").paginate():
            for role in page["Roles"]:
                if role.get("Path", "/").startswith("/aws-service-role/"):
                    continue  # AWS service-linked roles are noise
                m.add("aws_iam_role_info", {"name": role["RoleName"],
                                            "path": role.get("Path", "/")})
        for page in iam.get_paginator("list_policies").paginate(Scope="Local"):
            for policy in page["Policies"]:
                m.add("aws_iam_policy_info", {"name": policy["PolicyName"],
                                              "attached": policy.get("AttachmentCount", 0)})
        for page in iam.get_paginator("list_instance_profiles").paginate():
            for profile in page["InstanceProfiles"]:
                m.add("aws_iam_instance_profile_info",
                      {"name": profile["InstanceProfileName"]})
    except Exception as exc:  # noqa: BLE001
        errors.record("iam", "-", "list", exc)

    # ── rollups ─────────────────────────────────────────────────────────────────────
    for (region, itype, state), count in sorted(ec2_count.items()):
        m.add("aws_ec2_instances", {"region": region, "type": itype, "state": state}, count)
    for (region, state), count in sorted(ebs_count.items()):
        m.add("aws_ebs_volumes", {"region": region, "state": state}, count)
    for kind, value in (("security_group", counts["sg"]),
                        ("ebs_snapshot", counts["snapshot"]),
                        ("elastic_ip", counts["eip"]),
                        ("elastic_ip_unassociated", eip_unassoc),
                        ("ec2_fleet", counts["fleet"]),
                        ("ec2_launch_template", counts["launch_template"])):
        m.add("aws_detail_resource_count", {"kind": kind}, value)

    total = 0.0
    for region, value in sorted(cost_hr.items()):
        m.add("aws_estimated_cost_usd_per_hour", {"region": region}, f"{value:.4f}")
        total += value
    m.add("aws_estimated_cost_usd_per_hour", {"region": "all"}, f"{total:.4f}")
    ebs_mo = storage_gb["ebs"] * EBS_GB_MO
    snap_mo = storage_gb["snapshot"] * SNAP_GB_MO
    s3_mo = storage_gb["s3"] * S3_GB_MO
    eip_mo = eip_unassoc * EIP_UNASSOC_MO
    for kind, value in (("ebs", ebs_mo), ("ebs_snapshot", snap_mo), ("s3", s3_mo),
                        ("elastic_ip", eip_mo),
                        ("all", ebs_mo + snap_mo + s3_mo + eip_mo)):
        m.add("aws_estimated_storage_cost_usd_per_month", {"kind": kind}, f"{value:.2f}")


def _s3_size(bucket, region, errors):
    """(bytes, objects) from CloudWatch S3 daily metrics — cheap vs listing a big bucket."""
    try:
        cw = boto3.client("cloudwatch",
                          region_name=region if region != "unknown" else HOME_REGION,
                          config=_boto)

        def stat(metric, storage):
            resp = cw.get_metric_statistics(
                Namespace="AWS/S3", MetricName=metric,
                Dimensions=[{"Name": "BucketName", "Value": bucket},
                            {"Name": "StorageType", "Value": storage}],
                StartTime=time.time() - 3 * 86400, EndTime=time.time(),
                Period=86400, Statistics=["Average"])
            points = sorted((resp.get("Datapoints") or []), key=lambda p: p["Timestamp"])
            return points[-1]["Average"] if points else 0.0
        return stat("BucketSizeBytes", "StandardStorage"), stat("NumberOfObjects", "AllStorageTypes")
    except Exception as exc:  # noqa: BLE001 — size is best-effort, but still reported
        errors.record("cloudwatch", region, "get-metric-statistics", exc)
        return 0.0, 0.0


# ── top level ────────────────────────────────────────────────────────────────────────
def build_metrics():
    m, errors = Metrics(), Errors()
    m.declare("aws_inventory_mr_index_ok",
              "1 if the live Crossplane managed-resource set was read in full from the "
              "Kubernetes API. 0 means managed-vs-orphaned is UNDECIDABLE this scrape.")
    m.declare("aws_inventory_mr_kinds",
              "Managed-resource kinds discovered from the API server and how many were "
              "listable. discovered != listed means RBAC is missing an API group.")
    m.declare("aws_inventory_mr_resources", "Live Crossplane managed resources seen.")
    m.declare("aws_inventory_classification_trustworthy",
              "1 only if the MR index was read in full, every scanned region succeeded "
              "and no Resource Explorer result set was truncated.")
    m.declare("aws_inventory_coverage_complete",
              "1 only if, in addition, every enabled region was scanned by some source "
              "and an AGGREGATOR index exists. 0 = known blind spots; see "
              "aws_inventory_region_unindexed.")

    mr_index, mr_ok, kinds_found, kinds_listed = managed_resource_index(errors)
    m.add("aws_inventory_mr_index_ok", None, 1 if mr_ok else 0)
    m.add("aws_inventory_mr_kinds", {"state": "discovered"}, kinds_found)
    m.add("aws_inventory_mr_kinds", {"state": "listed"}, kinds_listed)
    m.add("aws_inventory_mr_resources", None, sum(len(v) for v in mr_index.values()))

    regions, regions_ok = _regions(errors)
    merged, complete_all, scanned, aggregator = inventory(m, errors, mr_index, mr_ok, regions)

    if DETAIL_SWEEP and regions:
        detail_sweep(m, errors, mr_index, mr_ok, regions)

    m.declare("aws_inventory_scrape_errors",
              "Failures in the last sweep by source/region/op. Non-zero means the "
              "inventory is incomplete — read it before believing any count.")
    m.declare("aws_inventory_scrape_error_info",
              "One failure with its AWS/HTTP error code as a label, so a permissions "
              "failure is distinguishable from an empty result without reading logs.")
    for (source, region, op, code), count in sorted(errors.items.items()):
        m.add("aws_inventory_scrape_errors",
              {"source": source, "region": region, "op": op}, count)
        m.add("aws_inventory_scrape_error_info",
              {"source": source, "region": region, "op": op, "code": code}, count)

    trustworthy = mr_ok and not len(errors) and complete_all
    coverage = (trustworthy and regions_ok and bool(regions)
                and all(r in scanned for r in regions) and aggregator)
    m.add("aws_inventory_classification_trustworthy", None, 1 if trustworthy else 0)
    m.add("aws_inventory_coverage_complete", None, 1 if coverage else 0)

    m.declare("aws_inventory_regions_swept", "Enabled regions this sweep covered.")
    m.add("aws_inventory_regions_swept", None, len(scanned))
    m.declare("aws_inventory_regions_enabled", "Enabled regions in the account.")
    m.add("aws_inventory_regions_enabled", None, len(regions))
    m.declare("aws_inventory_scrape_success",
              "1 if the sweep completed without errors. Deliberately NOT the trust "
              "signal: see aws_inventory_classification_trustworthy for whether the "
              "three-bucket classification can be believed.")
    m.add("aws_inventory_scrape_success", None, 1 if not len(errors) else 0)
    m.declare("aws_inventory_last_scrape_timestamp_seconds", "Unix time of the last sweep.")
    m.add("aws_inventory_last_scrape_timestamp_seconds", None, int(time.time()))
    _log(f"swept regions={len(scanned)}/{len(regions)} resources={len(merged)} "
         f"mr_kinds={kinds_listed}/{kinds_found} mr_ok={mr_ok} errors={len(errors)}")
    return m.render()


def _refresh_loop():
    global _snapshot
    while True:
        try:
            snap = build_metrics()
            with _lock:
                _snapshot = snap
            _log(f"snapshot refreshed ({snap.count(chr(10))} lines)")
        except Exception as exc:  # noqa: BLE001 — keep serving the last good snapshot
            _log(f"refresh loop error: {exc}\n{traceback.format_exc()}")
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
         f"regions={REGIONS_ENV or 'ALL'}, resource-explorer={RE_ENABLED}, "
         f"tagging-api={TAGGING_ENABLED}, detail-sweep={DETAIL_SWEEP})")
    ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
