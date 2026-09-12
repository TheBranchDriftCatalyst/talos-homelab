"""CloudNativePG failover — chaos/DR test  (epic TALOS-23l.5)

Validates the CloudNativePG HA design: the operator is live, every declared Postgres Cluster is
streaming-replicated and healthy, and — when the primary dies — CNPG promotes a replica, repoints
the `-rw` Service, and NO committed data is lost. The destructive tier MEASURES promotion time.

READ-ONLY (always) asserts the machinery EXISTS + is healthy. DESTRUCTIVE (armed: pytest
--destructive / CNPG_DR_DESTRUCTIVE=1) runs ONLY against a throwaway canary Cluster in an isolated
namespace (never a prod DB). Everything runs through kubectl exec/get; data I/O uses psql in-pod.

Needs `kubectl` (context = the cluster) on PATH.
"""
import json
import os
import re
import sys
import tempfile
import time
from pathlib import Path

import pytest

_ROOT = next(p for p in Path(__file__).resolve().parents if (p / "pytest.ini").exists())
sys.path.insert(0, str(_ROOT / "tests"))

from lib import dr  # noqa: E402

pytestmark = pytest.mark.disaster_recovery

# ---- config (env-overridable, preserved from the Jest suite) ----
OPERATOR_NS = os.environ.get("CNPG_OPERATOR_NS", "databases")
CLUSTER_NS = os.environ.get("CNPG_CLUSTER_NS", "")  # "" = all namespaces
CANARY_NS = os.environ.get("CNPG_CANARY_NS", "cnpg-dr-canary")
CANARY = os.environ.get("CNPG_CANARY", "cnpg-canary")
CANARY_INSTANCES = int(os.environ.get("CNPG_CANARY_INSTANCES", "2"))
CANARY_STORAGE = os.environ.get("CNPG_CANARY_STORAGE_CLASS", "fatboy-nfs-appdata")
CANARY_STORAGE_SIZE = os.environ.get("CNPG_CANARY_STORAGE_SIZE", "1Gi")
CANARY_ROWS = int(os.environ.get("CNPG_CANARY_ROWS", "1000"))
MAX_PROMOTION_S = float(os.environ.get("CNPG_MAX_PROMOTION_S", "60"))
MAX_RW_REPOINT_S = float(os.environ.get("CNPG_MAX_RW_REPOINT_S", "60"))
CNPG_HEALTHY_PHASE = "Cluster in healthy state"
DESTRUCTIVE_ENV = "CNPG_DR_DESTRUCTIVE"

M = dr.Metrics("CNPG DR")
_state = {}  # shared across the destructive scenarios


@pytest.fixture(autouse=True)
def _require_cluster():
    dr.require_cluster()


@pytest.fixture(scope="module", autouse=True)
def _summary():
    yield
    M.summary()


# ---- helpers ----
def ns_flag(ns):
    return f"-n {ns}" if ns else "-A"


def list_clusters():
    raw = dr.kubectl(f"get cluster.postgresql.cnpg.io {ns_flag(CLUSTER_NS)} -o json")
    if not raw or re.search(r"the server doesn't have a resource type|No resources found", raw):
        return []
    try:
        parsed = json.loads(raw)
    except Exception:
        return []
    out = []
    for c in parsed.get("items", []):
        st, spec = c.get("status", {}), c.get("spec", {})
        out.append({"name": c["metadata"]["name"], "ns": c["metadata"]["namespace"],
                    "instances": spec.get("instances"), "ready": st.get("readyInstances"),
                    "phase": st.get("phase", ""), "primary": st.get("currentPrimary", "")})
    return out


def current_primary(name, ns):
    return dr.kubectl(f"get cluster.postgresql.cnpg.io {name} -n {ns} -o jsonpath={{.status.currentPrimary}}")


def pod_ip(pod, ns):
    return dr.kubectl(f"get pod {pod} -n {ns} -o jsonpath={{.status.podIP}}")


def endpoint_ips(svc, ns):
    jp = "\"jsonpath={range .subsets[*].addresses[*]}{.ip}{'\\n'}{end}\""
    raw = dr.kubectl(f"get endpoints {svc} -n {ns} -o {jp}")
    return [s.strip() for s in raw.splitlines() if s.strip()]


def psql(pod, ns, db, sql):
    q = sql.replace('"', '\\"')
    return dr.kubectl(f'exec {pod} -n {ns} -c postgres -- psql -U postgres -d {db} -tAc "{q}"', timeout=60)


def operator_available_replicas():
    raw = dr.kubectl(
        f'get deploy -n {OPERATOR_NS} -l app.kubernetes.io/name=cloudnative-pg '
        f'-o jsonpath="{{.items[*].status.availableReplicas}}"')
    return sum(int(x) for x in (raw or "").split() if x.isdigit())


def canary_manifest():
    return f"""apiVersion: v1
kind: Namespace
metadata:
  name: {CANARY_NS}
  labels:
    app.kubernetes.io/name: cnpg-dr-canary
    catalyst.io/ephemeral: "true"
---
apiVersion: postgresql.cnpg.io/v1
kind: Cluster
metadata:
  name: {CANARY}
  namespace: {CANARY_NS}
  labels:
    catalyst.io/ephemeral: "true"
spec:
  instances: {CANARY_INSTANCES}
  imagePullPolicy: IfNotPresent
  primaryUpdateStrategy: unsupervised
  storage:
    size: {CANARY_STORAGE_SIZE}
    storageClass: {CANARY_STORAGE}
  monitoring:
    enablePodMonitor: false
  bootstrap:
    initdb:
      database: app
      owner: app
  resources:
    requests:
      cpu: 50m
      memory: 128Mi
"""


def create_canary():
    with tempfile.NamedTemporaryFile("w", suffix=".yaml", delete=False) as f:
        f.write(canary_manifest())
        path = f.name
    try:
        dr.kubectl(f"apply -f {path}", check=True)
    finally:
        os.unlink(path)

    def _healthy():
        raw = dr.kubectl(f"get cluster.postgresql.cnpg.io {CANARY} -n {CANARY_NS} -o json")
        if not raw:
            return False
        try:
            c = json.loads(raw)
        except Exception:
            return False
        st, spec = c.get("status", {}), c.get("spec", {})
        return st.get("readyInstances") == spec.get("instances") and bool(st.get("currentPrimary"))

    dr.wait_until(_healthy, timeout_s=420, interval_s=5)


def delete_canary():
    dr.kubectl(f"delete namespace {CANARY_NS} --ignore-not-found --wait=false")


@pytest.fixture(scope="module")
def canary():
    if not dr.armed(DESTRUCTIVE_ENV):
        yield None
        return
    dr.require_cluster()
    create_canary()
    yield CANARY
    delete_canary()


# ---- READ-ONLY tier (always runs) ----
def test_cnpg_operator_available():
    avail = operator_available_replicas()
    M.record("CNPG operator Available", avail, ">= 1", avail >= 1)
    assert avail >= 1, f"operator availableReplicas={avail}"


def test_at_least_one_cluster_cr():
    n = len(list_clusters())
    M.record("CNPG Clusters discovered", n, ">= 1", n >= 1)
    assert n >= 1, "no postgresql.cnpg.io/Cluster CRs found"


def test_every_cluster_healthy():
    clusters = list_clusters()
    all_ok = len(clusters) > 0
    detail = []
    for c in clusters:
        healthy = c["ready"] == c["instances"] and c["phase"] == CNPG_HEALTHY_PHASE and bool(c["primary"])
        all_ok = all_ok and healthy
        if not healthy:
            detail.append(f"{c['ns']}/{c['name']}: {c['ready']}/{c['instances']} phase={c['phase']}")
    M.record("All clusters healthy (ready==instances)",
             f"{len(clusters)}/{len(clusters)}" if all_ok else "DEGRADED", "all", all_ok)
    assert all_ok, f"degraded clusters: {detail}"


def test_every_cluster_rw_points_at_primary():
    clusters = list_clusters()
    all_ok = len(clusters) > 0
    detail = []
    for c in clusters:
        eps = endpoint_ips(f"{c['name']}-rw", c["ns"])
        prim_ip = pod_ip(c["primary"], c["ns"]) if c["primary"] else ""
        ok = len(eps) >= 1 and (not prim_ip or prim_ip in eps)
        all_ok = all_ok and ok
        if not ok:
            detail.append(f"{c['ns']}/{c['name']}-rw → {eps} (primary {prim_ip})")
    M.record("-rw Services point at primary", "all" if all_ok else "MISMATCH", "all", all_ok)
    assert all_ok, f"-rw endpoint mismatch: {detail}"


# ---- DESTRUCTIVE tier (armed only; canary) ----
@pytest.mark.destructive
def test_seed_rows_to_canary_primary(canary):
    dr.require_destructive(DESTRUCTIVE_ENV)
    prim = current_primary(CANARY, CANARY_NS)
    psql(prim, CANARY_NS, "app", "CREATE TABLE IF NOT EXISTS dr_probe (id bigserial primary key, note text);")
    psql(prim, CANARY_NS, "app",
         f"INSERT INTO dr_probe (note) SELECT 'dr-'||g FROM generate_series(1, {CANARY_ROWS}) g;")
    psql(prim, CANARY_NS, "app", "CHECKPOINT; SELECT pg_switch_wal();")
    count = int(psql(prim, CANARY_NS, "app", "SELECT count(*) FROM dr_probe;") or "0")
    _state["seeded"] = count
    M.record("Seed rows written to primary", count, f"= {CANARY_ROWS}", count == CANARY_ROWS)
    assert count == CANARY_ROWS, f"seeded {count} rows, expected {CANARY_ROWS}"


@pytest.mark.destructive
def test_failover_promotes_replica(canary):
    dr.require_destructive(DESTRUCTIVE_ENV)
    old_primary = current_primary(CANARY, CANARY_NS)
    t0 = time.time()
    dr.kubectl(f"delete pod {old_primary} -n {CANARY_NS} --wait=false")

    new_primary = {"v": ""}

    def _promoted():
        p = current_primary(CANARY, CANARY_NS)
        if p and p != old_primary:
            new_primary["v"] = p
            return True
        return False

    promoted = dr.wait_until(_promoted, timeout_s=MAX_PROMOTION_S * 2, interval_s=1)
    promo_s = time.time() - t0
    assert promoted, f"no replica promoted within {MAX_PROMOTION_S * 2}s"
    dr.assert_within(promo_s, MAX_PROMOTION_S, "replica promotion time")
    M.record("Replica promotion time", f"{promo_s:.2f}s", f"<= {MAX_PROMOTION_S}s",
             promoted and promo_s <= MAX_PROMOTION_S)
    M.record("New primary elected", new_primary["v"] or "none", f"!= {old_primary}", promoted)

    # -rw Service must repoint to the NEW primary's pod IP
    t_svc = time.time()
    new_ip = {"v": ""}

    def _repointed():
        new_ip["v"] = pod_ip(new_primary["v"], CANARY_NS)
        if not new_ip["v"]:
            return False
        eps = endpoint_ips(f"{CANARY}-rw", CANARY_NS)
        return len(eps) >= 1 and new_ip["v"] in eps

    repointed = dr.wait_until(_repointed, timeout_s=MAX_RW_REPOINT_S, interval_s=1)
    svc_s = time.time() - t_svc
    assert repointed, f"{CANARY}-rw did not repoint at {new_primary['v']}"
    dr.assert_within(svc_s, MAX_RW_REPOINT_S, "-rw Service repoint time")
    M.record("-rw Service repoint time", f"{svc_s:.2f}s", f"<= {MAX_RW_REPOINT_S}s",
             repointed and svc_s <= MAX_RW_REPOINT_S)

    # committed rows must survive the failover on the new primary
    count = {"v": 0}

    def _rows_survived():
        count["v"] = int(psql(new_primary["v"], CANARY_NS, "app", "SELECT count(*) FROM dr_probe;") or "0")
        return count["v"] == CANARY_ROWS

    survived = dr.wait_until(_rows_survived, timeout_s=60, interval_s=2)
    M.record("Rows survive failover", count["v"], f"= {CANARY_ROWS}", survived)
    assert count["v"] == CANARY_ROWS, f"{count['v']}/{CANARY_ROWS} rows survived the failover"


@pytest.mark.destructive
def test_canary_returns_to_full_health(canary):
    dr.require_destructive(DESTRUCTIVE_ENV)

    def _recovered():
        raw = dr.kubectl(f"get cluster.postgresql.cnpg.io {CANARY} -n {CANARY_NS} -o json")
        if not raw:
            return False
        try:
            c = json.loads(raw)
        except Exception:
            return False
        st, spec = c.get("status", {}), c.get("spec", {})
        return st.get("readyInstances") == spec.get("instances") and st.get("phase") == CNPG_HEALTHY_PHASE

    recovered = dr.wait_until(_recovered, timeout_s=300, interval_s=5)
    M.record("Canary re-attaches to full health", "healthy" if recovered else "DEGRADED", "healthy", recovered)
    assert recovered, "canary did not return to all-instances-ready + healthy phase"
