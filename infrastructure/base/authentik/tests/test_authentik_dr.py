"""Authentik SSO — disaster-recovery / chaos test  (TALOS-23l.4)

Authentik is a CLUSTER-WIDE AUTH SPOF: a single-replica authentik-server backed by a CNPG postgres
and a Dragonfly redis. Every OIDC/forward-auth app in the fleet rides on it. This suite validates
the DR machinery EXISTS + is healthy, and MEASURES OIDC downtime when the single server pod is
killed.

READ-ONLY (always) only observes. DESTRUCTIVE (armed: pytest --destructive /
AUTHENTIK_DR_DESTRUCTIVE=1) deletes the stateless authentik-server pod (postgres/redis/PVC strictly
off-limits) and measures recovery. The OIDC endpoint is in-cluster only, so every HTTP probe runs
THROUGH a pod.

Needs `kubectl` (context = the cluster) on PATH.
"""
import os
import re
import sys
import time
from pathlib import Path

import pytest

_ROOT = next(p for p in Path(__file__).resolve().parents if (p / "pytest.ini").exists())
sys.path.insert(0, str(_ROOT / "tests"))

from lib import dr  # noqa: E402

pytestmark = pytest.mark.disaster_recovery

# ---- config (env-overridable, preserved from the Jest suite) ----
NS = os.environ.get("AUTHENTIK_NS", "authentik")
SERVER_DEPLOY = os.environ.get("AUTHENTIK_SERVER_DEPLOY", "authentik-server")
WORKER_DEPLOY = os.environ.get("AUTHENTIK_WORKER_DEPLOY", "authentik-worker")
SERVER_SVC = os.environ.get("AUTHENTIK_SERVER_SVC", "authentik-server")
SERVER_LABEL = os.environ.get("AUTHENTIK_SERVER_LABEL", "app.kubernetes.io/component=server")
PG_CLUSTER = os.environ.get("AUTHENTIK_PG_CLUSTER", "authentik-postgres")
OIDC_HOST = os.environ.get("AUTHENTIK_OIDC_HOST", f"{SERVER_SVC}.{NS}.svc.cluster.local")
OIDC_SLUG = os.environ.get("AUTHENTIK_OIDC_SLUG", "litellm")
WELLKNOWN_PATH = os.environ.get(
    "AUTHENTIK_WELLKNOWN_PATH", f"/application/o/{OIDC_SLUG}/.well-known/openid-configuration")
WELLKNOWN_URL = f"http://{OIDC_HOST}{WELLKNOWN_PATH}"
CURL_IMAGE = os.environ.get("AUTHENTIK_CURL_IMAGE", "curlimages/curl:8.10.1")
PROBE_POD = os.environ.get("AUTHENTIK_PROBE_POD", "authentik-dr-probe")
MAX_RECOVERY_S = float(os.environ.get("AUTHENTIK_MAX_RECOVERY_S", "180"))
MAX_DOWNTIME_S = float(os.environ.get("AUTHENTIK_MAX_DOWNTIME_S", "180"))
DESTRUCTIVE_ENV = "AUTHENTIK_DR_DESTRUCTIVE"

M = dr.Metrics("Authentik DR")


@pytest.fixture(autouse=True)
def _require_cluster():
    dr.require_cluster()


@pytest.fixture(scope="module", autouse=True)
def _summary():
    yield
    M.summary()


# ---- helpers ----
def ready_replicas(deploy):
    return int(dr.kubectl(f"get deploy {deploy} -n {NS} -o jsonpath={{.status.readyReplicas}}") or "0")


def spec_replicas(deploy):
    return int(dr.kubectl(f"get deploy {deploy} -n {NS} -o jsonpath={{.spec.replicas}}") or "0")


def server_pod():
    return dr.kubectl(f"get pods -n {NS} -l {SERVER_LABEL} -o jsonpath={{.items[0].metadata.name}}")


def is_ok(code):
    return bool(re.match(r"^2\d\d$", str(code)))


def oidc_code_one_shot(tries=3):
    for _ in range(tries):
        code = dr.kubectl(
            f"run adr-{int(time.time() * 1000)} -n {NS} --rm -i --restart=Never --image={CURL_IMAGE} "
            f'--command -- curl -s -o /dev/null -w "%{{http_code}}" --max-time 8 {WELLKNOWN_URL}',
            timeout=70)
        m = re.search(r"(\d{3})(?!\d)", code or "")
        if m:
            return m.group(1)
        time.sleep(1.5)
    return "000"


def create_probe():
    dr.kubectl(f"run {PROBE_POD} -n {NS} --restart=Never --image={CURL_IMAGE} --command -- sleep 3600")
    dr.kubectl(f"wait --for=condition=Ready pod/{PROBE_POD} -n {NS} --timeout=120s")


def delete_probe():
    dr.kubectl(f"delete pod {PROBE_POD} -n {NS} --ignore-not-found --wait=false")


def probe_code():
    code = dr.kubectl(
        f'exec {PROBE_POD} -n {NS} -- curl -s -o /dev/null -w "%{{http_code}}" '
        f"--max-time 3 {WELLKNOWN_URL}", timeout=15)
    m = re.search(r"(\d{3})(?!\d)", code or "")
    return m.group(1) if m else "000"


@pytest.fixture(scope="module")
def probe_pod():
    if not dr.armed(DESTRUCTIVE_ENV):
        yield None
        return
    dr.require_cluster()
    create_probe()
    yield PROBE_POD
    delete_probe()


# ---- READ-ONLY tier (always runs) ----
def test_authentik_server_ready():
    ready = ready_replicas(SERVER_DEPLOY)
    replicas = spec_replicas(SERVER_DEPLOY)
    M.record("authentik-server Ready", f"{ready}/{replicas}", ">= 1", ready >= 1)
    assert ready >= 1, f"{SERVER_DEPLOY} readyReplicas={ready}"


def test_authentik_worker_ready():
    ready = ready_replicas(WORKER_DEPLOY)
    M.record("authentik-worker Ready", "yes" if ready >= 1 else "no", "yes", ready >= 1)
    assert ready >= 1, f"{WORKER_DEPLOY} readyReplicas={ready}"


def test_oidc_wellknown_returns_200():
    code = oidc_code_one_shot()
    M.record("OIDC well-known endpoint 200", code, "2xx", is_ok(code))
    assert is_ok(code), f"GET {WELLKNOWN_PATH} → {code}"


def test_cnpg_authentik_postgres_healthy():
    phase = dr.kubectl(f"get cluster {PG_CLUSTER} -n {NS} -o jsonpath={{.status.phase}}")
    ready_inst = int(dr.kubectl(f"get cluster {PG_CLUSTER} -n {NS} -o jsonpath={{.status.readyInstances}}") or "0")
    instances = int(dr.kubectl(f"get cluster {PG_CLUSTER} -n {NS} -o jsonpath={{.spec.instances}}") or "0")
    healthy = bool(re.search(r"healthy", phase, re.I)) and instances > 0 and ready_inst == instances
    M.record("CNPG authentik-postgres healthy", f"{ready_inst}/{instances}", "all ready", healthy)
    assert healthy, f"{PG_CLUSTER} phase={phase or '(none)'} ready={ready_inst}/{instances}"


# ---- DESTRUCTIVE tier (armed only) ----
@pytest.mark.destructive
def test_server_kill_oidc_recovers_and_measures_downtime(probe_pod):
    dr.require_destructive(DESTRUCTIVE_ENV)
    before = server_pod()
    probe = dr.Probe(lambda: is_ok(probe_code()), interval_s=0.5)
    time.sleep(1.5)  # establish a healthy baseline
    dr.kubectl(f"delete pod {before} -n {NS} --wait=false")
    t0 = time.time()
    recovered = dr.wait_until(lambda: is_ok(probe_code()), timeout_s=MAX_RECOVERY_S, interval_s=1)
    recovery_s = time.time() - t0
    time.sleep(3)  # capture the tail of the recovery
    probe.stop()
    dt = probe.worst_downtime()
    still_one = spec_replicas(SERVER_DEPLOY) == 1

    dr.assert_within(recovery_s, MAX_RECOVERY_S, "OIDC recovery time")
    dr.assert_within(dt, MAX_DOWNTIME_S, "OIDC worst downtime")
    M.record("OIDC recovery time (server kill)", f"{recovery_s:.2f}s", f"<= {MAX_RECOVERY_S}s",
             recovered and recovery_s <= MAX_RECOVERY_S)
    M.record("OIDC worst downtime (server kill)", f"{dt:.2f}s", f"<= {MAX_DOWNTIME_S}s",
             recovered and dt <= MAX_DOWNTIME_S)
    M.record("OIDC availability during kill", f"{probe.availability() * 100:.1f}%", "-", recovered)
    M.record("Server still single-replica", "yes" if still_one else "no", "yes", still_one)
    assert recovered, "OIDC well-known did not recover to 200 after server kill"
