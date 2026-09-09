# TESTING.md

## TL;DR

This repo tests infrastructure two ways, and both follow the same discipline —
**safe/offline by default, destructive/live behind an explicit flag**:

1. **DR / resilience layer** (Jest) — per-component `*-dr.test.js` suites that prove
   the recovery machinery exists and, when armed, inject faults and measure recovery.
2. **Security-posture layer** (Python) — `scripts/security/test_security_posture.py`
   asserts security contracts against the manifests (offline) and against the running
   cluster (`--live`).

```bash
# DR layer (Jest)
npm test                       # read-only: every DR suite's non-destructive checks
npm run test:dr                # ARMED: destructive chaos (homelab only)
npx jest --selectProjects traefik-dr    # one suite

# Security-posture layer (Python)
python scripts/security/test_security_posture.py          # offline manifest contracts
python scripts/security/test_security_posture.py --live   # + running-system assertions
```

**Rule going forward:** every security fix ships with a paired posture test — an
**offline contract** (the manifest is fixed) and, where feasible, a **`--live` assertion**
(the hole is actually closed). A fix without a test is a regression waiting to happen.

---

## The two layers

| | **DR / resilience** | **Security posture** |
|---|---|---|
| Question | "When X fails, does it recover?" | "Is X configured and behaving securely?" |
| Runner | Jest (Node) | Python `unittest` |
| Location | `infrastructure/base/<c>/tests/*-dr.test.js`, `tests/etcd-dr/` | `scripts/security/test_security_posture.py` (+ `scripts/security/check-*.py`) |
| Aggregator | root `jest.config.js` `projects[]` | one script, two `TestCase` classes |
| Safe default | read-only observation | offline manifest contracts |
| Guarded mode | `*_DESTRUCTIVE=1` env → fault injection | `--live` → running-system checks |
| CI | (local / on-demand) | `.github/workflows/security-posture.yaml` |
| Needs | `kubectl` (cluster context) | PyYAML always; `kubectl` + LAN for `--live` |

Both layers **never mutate real data or black-hole a real route by accident** — chaos
only ever targets throwaway routes and self-healing infra pods; the live security checks
are read-only bar one harmless synthetic-header GET.

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

`scripts/security/test_security_posture.py` — two `unittest.TestCase` classes:

- **`RepositoryPosture`** (offline, always runs): asserts security contracts against the
  GitOps manifests — e.g. sensitive headers not retained, CrowdSec enforcement has no
  unbounded fail-open, HA has no single-replica/co-location, honeypot/tarpit carry no API
  token. Helpers: `document(path)` (load a manifest), `crowdsec_values()`, `predicate()`
  (evaluate the host/path policy subset), and (live) `kube()` / `pod_list()`.
- **`RunningSystemPosture`** (`--live` only): asserts the same contracts against the running
  cluster — live AppSec exemptions are host-scoped, native config compiles, simulation name
  matches runtime, sensitive headers absent from the actual access log, etc.

Companion scripts (`scripts/security/check-crowdsec-*.py`, `test-crowdsec-*.py`,
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
