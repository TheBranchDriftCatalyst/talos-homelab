"""crossplane-demo — operator catalog integration test (companion to the pihole/vpn DR suites).

Verifies the self-service operator catalog (TALOS-ja5) end-to-end, in two tiers per subsystem:
  CRD/health  — the provisioned CR exists and its operator reconciled it to Ready.
  functional  — the Go "flex" pod actually exercised the backend (bucket/publish-consume/set-get/
                insert-query/index-search/workflow/celery/crossplane) and reports OK.

Checks SKIP cleanly when the cluster is unreachable. Needs `kubectl` (context = the cluster) on
PATH. NS = crossplane-demo.
"""
import json
import os
import sys
from pathlib import Path

import pytest

# make `from lib import dr` resolve for this co-located suite regardless of how pytest is invoked
_ROOT = next(p for p in Path(__file__).resolve().parents if (p / "pytest.ini").exists())
sys.path.insert(0, str(_ROOT / "tests"))

from lib import dr  # noqa: E402

pytestmark = pytest.mark.integration

# ---- config (env-overridable, preserved from the Jest suite) ----
NS = os.environ.get("DEMO_NS", "crossplane-demo")
FLEX = os.environ.get("FLEX_DEPLOY", "demo-flex")

M = dr.Metrics("crossplane-demo — subsystem matrix")


@pytest.fixture(autouse=True)
def _require_cluster():
    dr.require_cluster()


@pytest.fixture(scope="module", autouse=True)
def _summary():
    yield
    M.summary()


# ---- CRD/health tier: each provisioned CR exists + reconciled Ready ----
CRS = [
    ("RabbitMQ (RabbitmqCluster)", "rabbitmqclusters.rabbitmq.com", "demo-rabbit",
     "-o jsonpath={.status.conditions[?(@.type=='AllReplicasReady')].status}", "True"),
    ("Dragonfly (Dragonfly)", "dragonflies.dragonflydb.io", "demo",
     "-o jsonpath={.status.phase}", "Ready"),
    ("ClickHouse (ClickHouseInstallation)", "clickhouseinstallations.clickhouse.altinity.com", "demo",
     "-o jsonpath={.status.status}", "Completed"),
    ("OpenSearch (OpenSearchCluster)", "opensearchclusters.opensearch.org", "demo",
     "-o jsonpath={.status.phase}", "RUNNING"),
    ("KEDA (ScaledObject)", "scaledobjects.keda.sh", "demo-celery",
     "-o jsonpath={.status.conditions[?(@.type=='Ready')].status}", "True"),
    ("Argo (WorkflowTemplate)", "workflowtemplates.argoproj.io", "demo-hello", "", ""),
    ("Crossplane (Object)", "objects.kubernetes.crossplane.io", "crossplane-made-this",
     "-o jsonpath={.status.conditions[?(@.type=='Ready')].status}", "True"),
]


@pytest.mark.parametrize("label,kind,name,ready,want", CRS, ids=[c[0] for c in CRS])
def test_crd_health(label, kind, name, ready, want):
    exists = dr.kubectl(f"get {kind} {name} -n {NS} -o name", check=False)
    ok = bool(exists)
    detail = name if exists else "not found"
    if ok and ready:
        reached = dr.wait_until(
            lambda: dr.kubectl(f"get {kind} {name} -n {NS} {ready}", check=False) == want,
            timeout_s=180, interval_s=5)
        ok = reached
        detail = f"{exists.split('/')[-1]} status={want}{'' if reached else ' (NOT reached)'}"
    M.record(label, "OK" if ok else "FAIL", "Ready", ok)
    assert ok, f"{label}: {detail}"


# ---- functional tier: the Go flex pod exercised every backend ----
def test_functional_flex_run_reports_every_subsystem_ok():
    pod = dr.kubectl(f"get pods -n {NS} -l app={FLEX} -o jsonpath={{.items[0].metadata.name}}", check=False)
    assert pod, "no demo-flex pod present"
    # run the checks in-pod (the flex binary supports -once → JSON on stdout)
    raw = dr.kubectl(f"exec {pod} -n {NS} -- /flex -once", check=False, timeout=120)
    parsed = None
    brace = raw.find("{")
    if brace >= 0:
        try:
            parsed = json.loads(raw[brace:])
        except json.JSONDecodeError:
            parsed = None
    assert parsed and isinstance(parsed.get("results"), list), \
        f"flex /run did not return JSON results: {raw[:120]}"
    for r in parsed["results"]:
        ok = r.get("ok") or r.get("skipped")
        M.record(f"flex:{r['subsystem']}", "OK" if r.get("ok") else ("skip" if r.get("skipped") else "FAIL"),
                 "ok", bool(ok))
    cfgm = dr.kubectl(f"get configmap crossplane-made-this -n {NS} -o name", check=False)
    M.record("crossplane ConfigMap", "present" if cfgm else "missing", "present", bool(cfgm))
    all_ok = parsed.get("all_ok") or all(r.get("ok") or r.get("skipped") for r in parsed["results"])
    assert all_ok, "flex reported a failing subsystem"
