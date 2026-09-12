# TESTING.md

## TL;DR

This repo tests infrastructure four ways, and all follow the same discipline —
**safe/offline by default, destructive/live behind an explicit flag**:

1. **DR / resilience layer** (Jest) — per-component `*-dr.test.js` suites that prove
   the recovery machinery exists and, when armed, inject faults and measure recovery.
2. **Security-posture layer** (Python) — `tests/security-posture/test_security_posture.py`
   asserts *per-fix* security contracts against the manifests (offline) and against the
   running cluster (`--live`) — proves each fixed finding **stays fixed**.
3. **Telemetry / observability layer** (Python) — `tests/telemetry/test_dashboards.py`
   audits every Grafana dashboard **panel-by-panel**: offline it checks each panel has a resolvable
   datasource + query; `--live` it executes every panel's query and asserts data returns (or the panel
   is a justified `EXPECTED_EMPTY`). Add a dashboard in `tests/telemetry/dashboards.py`.
4. **Ingress-accessibility layer** (Python) — `tests/ingress-accessibility/test_ingress_accessibility.py`
   renders the whole Flux tree and asserts *fleet-wide* ingress invariants ("what is
   reachable, from where, with what auth") offline, plus a `--live` accessibility probe —
   proves **no new route reintroduces a finding's shape**. Accepted risks live in
   `tests/ingress-accessibility/ingress_allowlists.py` (the review surface).

```bash
# DR layer (Jest)
npm test                       # read-only: every DR suite's non-destructive checks
npm run test:dr                # ARMED: destructive chaos (homelab only)
npx jest --selectProjects traefik-dr    # one suite

# Unified runner (pytest + Jest) — suites are pytest markers
task test                 # ALL suites, offline/read-only (suite-grouped dashboard)
task test:security        # Security Posture only         (pytest -m security_posture)
task test:ingress         # Ingress Accessibility only    (pytest -m ingress_accessibility; needs kustomize)
task test:live            # ALL Python suites + --live running-cluster/LAN probes (operator-run)
task test:dr              # Disaster Recovery (Jest)      ; task test:dr-armed for chaos
task test:list            # the catalog: every test by suite
```

>**Unified runner:** all Python suites run under **pytest**, tagged by **suite marker**
(`security_posture`, `ingress_accessibility`) so `pytest -m <suite>` runs that suite wherever its
tests live. Shared utils/fixtures live in `tests/conftest.py` + `tests/lib/helpers.py`; a suite-grouped
terminal reporter prints a per-suite pass/fail dashboard. `task test` runs everything (pytest + Jest DR).

**Rule going forward:** every security fix ships with a paired posture test — an
**offline contract** (the manifest is fixed) and, where feasible, a **`--live` assertion**
(the hole is actually closed). A fix without a test is a regression waiting to happen.

---

## The four layers

| | **DR / resilience** | **Security posture** | **Ingress accessibility** |
|---|---|---|---|
| Question | "When X fails, does it recover?" | "Does each fixed finding stay fixed?" | "What is reachable, from where, with what auth?" |
| Runner | Jest (Node) | pytest (`-m security_posture`) | pytest (`-m ingress_accessibility`) |
| Location | `infrastructure/base/<c>/tests/*-dr.test.js`, `tests/etcd-dr/` | `tests/security-posture/test_security_posture.py` | `tests/ingress-accessibility/test_ingress_accessibility.py` (+ `ingress_corpus.py`, `ingress_allowlists.py`) |
| Corpus | one component | per-fix manifest paths | **rendered** whole Flux tree (`kustomize build`) |
| Aggregator | root `jest.config.js` `projects[]` | `pytest` marker + `tests/conftest.py` | `pytest` marker + `tests/conftest.py` |
| Safe default | read-only observation | offline manifest contracts | offline rendered-corpus contracts |
| Guarded mode | `*_DESTRUCTIVE=1` env → fault injection | `--live` → running-system checks | `--live` → read-only LAN + in-cluster probe |
| CI | (local / on-demand) | `security-posture.yaml` job `contracts` | `security-posture.yaml` job `ingress-surface` |
| Needs | `kubectl` | PyYAML; `kubectl`+LAN for `--live` | PyYAML + **`kustomize`**; `kubectl`+LAN for `--live` |

All three layers **never mutate real data or black-hole a real route by accident** — chaos
only ever targets throwaway routes and self-healing infra pods; the live security + accessibility
checks are read-only bar one harmless synthetic-header GET.

**Division of labour (posture vs accessibility):** the security-posture layer pins each specific
remediation (`--api.insecure` absent, qBittorrent has no carve-out); the ingress-accessibility layer
enumerates the *whole surface* so a NEW route that reintroduces a finding's shape (an un-gated `/api`
carve-out on a different app, a dangling middleware ref, a raw-TCP proxy) is caught even though the
original fix is untouched. Each accepted exception is a reviewed entry in `ingress_allowlists.py`
carrying a rationale + a `TALOS-` issue id — so relaxing a contract is a visible PR diff, not a
silently-passing test.

---

## Layer 1 — DR / resilience (Jest)

Each deployable component with a failure mode carries a `tests/` suite proving its DR
story. Suites are registered in `jest.config.js` `projects[]` so one command runs them all.

- **Pattern:** read-only health/wiring checks always run; destructive scenarios (kill the
  serving pod, delete a PVC consumer, sever the primary) run **only** when the suite's
  `*_DESTRUCTIVE=1` flag is set, then measure recovery (e.g. ingress downtime, failover time).
- **Examples:** `traefik-dr` (kill serving Traefik pod, measure :80/:443 downtime — arm with
  `TRAEFIK_DR_DESTRUCTIVE=1`), `cnpg-dr` (Postgres primary failover), `velero-dr`
  (backup+restore), `etcd-dr` (snapshot freshness/integrity), `pihole-dr`, `vpn-dr`,
  `minio-dr`, `nfs-lifecycle-dr`, `lbipam-dr`, `authentik-dr`.
- **Run:** `npm test` (safe, via `scripts/jest-select.js`) · `npm run test:dr` (armed) ·
  `npx jest --selectProjects <name>` (one suite).
- **Add a suite:** create `infrastructure/base/<c>/tests/<c>-dr.test.js`, gate destruction
  behind a `<C>_DR_DESTRUCTIVE=1` env, and add the path to `jest.config.js` `projects[]`.

> Note: the per-suite `package.json` files were removed — the root is the single dependency
> root and Jest aggregates the suites as projects. `tests/etcd-dr/` lives at repo root
> because `talos-dr` was never a deployable component (test-only).

---

## Layer 2 — security posture (Python)

`tests/security-posture/test_security_posture.py` — two `unittest.TestCase` classes:

- **`RepositoryPosture`** (offline, always runs): asserts security contracts against the
  GitOps manifests — e.g. sensitive headers not retained, CrowdSec enforcement has no
  unbounded fail-open, HA has no single-replica/co-location, honeypot/tarpit carry no API
  token. Helpers: `document(path)` (load a manifest), `crowdsec_values()`, `predicate()`
  (evaluate the host/path policy subset), and (live) `kube()` / `pod_list()`.
- **`RunningSystemPosture`** (`--live` only): asserts the same contracts against the running
  cluster — live AppSec exemptions are host-scoped, native config compiles, simulation name
  matches runtime, sensitive headers absent from the actual access log, etc.

Companion scripts (`tests/security-posture/check-crowdsec-*.py`, `test-crowdsec-*.py`,
`test-bt-agent-preflight.py`) cover CrowdSec parser/registration/VPN specifics and the
bt-radar agent preflight. CI runs the offline contracts on every PR touching security paths
(`.github/workflows/security-posture.yaml`); `--live` is operator-run (needs cluster+LAN).

### Adding a security test for a fix

When you remediate a finding, add its test here so the fix cannot silently regress:

```python
# RepositoryPosture — offline contract: the manifest is fixed
def test_traefik_dashboard_not_unauthenticated_on_web(self):
    values = document('infrastructure/base/traefik/helmrelease.yaml')['spec']['values']
    args = values.get('additionalArguments', [])
    self.assertNotIn('--api.insecure=true', args)              # finding 001
    # dashboard IngressRoute must not be on the plaintext `web` entrypoint

# RunningSystemPosture — live assertion: the hole is actually closed (guarded by --live)
def test_traefik_dashboard_refuses_unauth(self):
    if not LIVE: self.skipTest('live')
    # unauth GET of the dashboard/api must NOT return 200 (expect 401/403/404)
```

Keep the offline contract cheap and deterministic (it runs in CI on every PR); put anything
needing the cluster behind `if not LIVE: self.skipTest(...)`.

---

## Offensive testing (red-team)

Point-in-time penetration tests live **outside** this repo, in the `pentest` framework
(`workspace/pentest/target-packages/talos-ingress/`): findings, reproductions, evidence,
and the report. The security-posture layer here is the **standing regression net** that
proves each finding stays fixed — offensive tooling finds new holes; posture tests keep the
old ones shut. The 2026-09 ingress engagement is tracked as beads epic **TALOS-lxz5**, whose
verification epic wires a posture test to every fix.

---

## Related Issues

<!-- Beads tracking for this doc -->
- TALOS-lxz5.7 — Verification harness: a security test per fix (this doc's go-forward rule)
- TALOS-23l.* — the DR test-suite series
- TALOS-hg7 — security-posture suite origin (honeypot / tarpit / CrowdSec)
