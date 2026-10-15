# mega-log-analysis

Turns the centralised error-log stream into a beads ticket tree, re-runnably.

This became possible on 2026-10-15, when `ServiceName` coverage went from 0.35% to 100%
(TALOS-7e6j). Before that, errors could not be attributed per service.

## TL;DR

```bash
task dev:logs:selftest                  # prove the classifiers fire
task dev:logs:census -- --save          # snapshot errors per service -> baseline/
task dev:logs:triage                    # misclassified / expected / real
task dev:logs:tickets                   # dry-run the L1/L2/L3 tree
task dev:logs:burndown                  # progress against the committed baseline
python3 scripts/mega-log-analysis/mega_log_analysis.py prompt <sig_id>   # swarm prompt
```

Every stage writes or reads a JSON artifact, so the ticket tree can be regenerated from a later
window without hand-editing. `tickets` is idempotent: each leaf embeds `sig:<id>` and a re-run
searches beads for that marker before filing.

## Layout

```text
scripts/mega-log-analysis/
├── mega_log_analysis.py   # the whole tool (stdlib + pyyaml)
├── expected.yaml          # errors that are not bugs, each with its evidence
├── baseline/              # committed census snapshots -> the burn-down
└── README.md              # this file, and the running findings log below
```

Modelled on `dev/helm-values-lint/`: self-contained tool directory, own task namespace, and a
`selftest` subcommand because *a check that reports success is not a check that ran*.

## Why `triage` exists

`SeverityText` cannot be trusted on its own. 40.7% of rows marked `error` say INFO, TRACE or WARN
in their own body. `triage` splits three ways:

| Verdict | Meaning | Who fixes it |
| --- | --- | --- |
| `misclassified` | the body states a non-error level | the ingest pipeline |
| `expected` | a real error that is not a bug, listed in `expected.yaml` | nobody, deliberately |
| `real` | everything else | the owning service |

`tickets` only files `real`. Filing a `misclassified` signature as an app bug sends an agent to
investigate `"Saved checkpoint for VPA"`.

---

## Findings (first run, 2026-10-15)

Window: 1h. Baseline: `baseline/census-2026-10-15T05-10-29Z.json`.

**18,112 errors/hour (5.03/sec) across 53 services** — 7.2% of all log volume.
**515 distinct signatures**, but 63 at ≥1/min cover 90.6% of the volume, and the top 20 cover
64.8%. The work is concentrated, not sprawling.

### 1. 46.3% of "errors" are not errors

| Verdict | Rows/h | Share |
| --- | --- | --- |
| real | 9,365 | 53.7% |
| JSON `"s":"I"` / `"level":"info"` | 1,877 | 10.8% |
| logfmt `level=info` | 1,805 | 10.3% |
| `TRC` (kyverno) | 1,674 | 9.6% |
| klog INFO (`I0115 …`) | 1,672 | 9.6% |
| klog WARN | 389 | 2.2% |
| no declared level, no error vocabulary | 362 | 2.1% |
| numeric level 30 (pino) | 301 | 1.7% |

Six services are **entirely** misclassified and vanish from the actionable set once triage runs:
`kyverno-admission-controller` (1,672/h, all TRACE), `clickstack-mongodb-svc` (928/h, Mongo
`"s":"I"` connection-accepted lines), `vpa-recommender` (864/h, klog `"Saved checkpoint for VPA"`),
`crowdsec-lapi` (743/h, logfmt info), `crowdsec-web-ui` (346/h, no declared level) and
`clickstack` (301/h, pino `level:30`).

This is why Phase 0 is a hard gate: without it, four agent sub-swarms investigate nothing.

**The measurement moved twice, and both times the gap was in this tool rather than the pipeline.**
31.4% -> 40.7% -> 46.3%:

1. The `tickets` dry-run surfaced logfmt `level=info` sitting in the `real` bucket for crowdsec-lapi
   and mimir — 94 signatures, 1,547 rows/h. Added `body_says_logfmt_*`, plus an `ERROR_WINS` guard,
   because mimir wraps an inner `level=info` component field inside an outer `level=error` line and
   the naive rule swallowed genuine errors.
2. Reviewing the proposed tree surfaced two more. `clickstack` writes pino **numeric** levels, and
   `SIG_EXPR` rewrites `{"level":30}` to `{"level":<n>}` — normalisation destroyed the only evidence
   of what the line was. Facts that cannot survive normalisation are now read from the RAW body in
   SQL (`LEVEL_NUM_EXPR`, `HAS_LEVEL_EXPR`, `HAS_ERRWORD_EXPR`). And `crowdsec-web-ui` declares no
   level at all, so no level-parsing rule can reach it; that needed a last-resort heuristic keyed on
   the **absence** of error vocabulary rather than the presence of progress words. Measured on a live
   hour it selects 362 rows while leaving 1,098 rows that also lack a level but do carry error
   vocabulary classified `real`.

### 2. One service, two one-line faults, 24% of all cluster errors

`traefik` at 4,491/h resolves to:

- `kubernetes service not found: catalyst-llm/sillytavern` — ~3,000/h across **two** IngressRoutes
  (`sillytavern` and `sillytavern-http`), i.e. two manifests referencing a Service that does not
  exist.
- `secret authentik/authentik-outpost-tls does not exist` — ~1,495/h from
  `ak-outpost-authentik-embedded-outpost`.

### 3. A real backup failure hiding in the noise

`postgresql` in `zipline` at 698/h: `Error invoking barman-cloud-check-wal-archive`,
`failed to run wal-archive`, `Error while handling GRPC request`. WAL archiving appears to be
failing continuously. This is the kind of finding the campaign exists for — it is indistinguishable
from log noise until errors are attributed per service.

### 4. Honeypot errors are not all attacker noise

`cowrie` at 552/h, of which 252/h is `builtins.AttributeError: 'Server' object has no attribute
'socket'` — a genuine Python crash, already filed as **TALOS-3qe4**. The operator's standing
decision for this campaign is *fix the app where possible* rather than suppress, which is why
`expected.yaml` ships empty.

---

## Log & metrics pipeline issues discovered

The running side-notes list. New entries go here as the campaign finds them; durable lessons get
distilled up into `SESSION_STATUS.md` → Standing gotchas rather than left as "X is broken today".

| # | Issue | Status |
| --- | --- | --- |
| 1 | **Severity misclassification** — 40.7% of `error` rows state a non-error level in their body. The ClickStack collector does not parse klog/logfmt/JSON levels. | Phase 0 of the mega epic |
| 2 | **Log body overwrites k8s metadata** — the collector flattens body JSON into `LogAttributes`, so a body key `namespace` beats the real one. 67 of 36,287 rows (0.185%); only `namespace`, only cross-namespace controllers. `ResourceAttributes['k8s.namespace.name']` is the trustworthy copy. | **TALOS-woqh** |
| 3 | **Dual-write misses short-lived pods** — Loki has CronJob output ClickStack never received (abuseipdb-reporter, 39 lines, pod lived 21s). Blocks Loki deletion. | **TALOS-atkc** |
| 4 | **No k8s metrics or k8s events in ClickStack** — only 54 metric names, all self-telemetry (`v8js.*`, `otelcol_*`). HyperDX's Kubernetes dashboard is blank for this reason, not the ServiceName one. | **TALOS-suxd.8** |
| 5 | **HyperDX ships its own browser telemetry to `localhost:4318`** — console shows `ERR_CONNECTION_REFUSED` on every page load. Cosmetic, upstream default. | unfiled |
| 6 | **HyperDX has a second login beneath Authentik** — forward-auth passes, then its own `/api/me` 401s and bounces to `/login`. | unfiled |

## Gotchas

1. **`alloy validate` does not check OTTL.** A bad statement passes validation and then makes Alloy
   refuse to start entirely. Use an `alloy run` probe on a minimal config. See memory
   `alloy-validate-does-not-check-ottl`.
2. **Signature truncation can over-split one cause.** traefik's missing-Service error appears as two
   signatures because two IngressRoutes name it. That is arguably correct — two manifests, two
   fixes — but shared root causes are deduped at the review step, not by the tool.
3. **`--apply` is deliberately not wired.** Propose-only is the standing rule for this campaign;
   the L2 list is reviewed with the operator before any tree is created.

---

## Related Issues

<!-- Beads tracking for this doc -->

- TALOS-woqh — ClickStack collector lets log body overwrite k8s metadata
- TALOS-atkc — dual-write misses short-lived pods
- TALOS-3qe4 — cowrie AttributeError tracebacks
- TALOS-7e6j — ServiceName empty (closed; what made this tool possible)
