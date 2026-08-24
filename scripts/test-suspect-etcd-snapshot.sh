#!/usr/bin/env bash
#
# test-suspect-etcd-snapshot.sh
#
# Probe the "etcd snapshot fsync storm" hypothesis from the 2026-05-29 council
# (TALOS-w4t). Manually triggers an etcd-backup CronJob, measures the disk
# commit-duration percentile and apiserver responsiveness BEFORE / DURING /
# AFTER the snapshot, and reports pass/fail.
#
# Related hypotheses:
#   TALOS-r10 — Flux mass-reconcile bursts saturating apiserver (Option A
#               applied 2026-05-30; observation window open).
#   TALOS-w4t — Snapshot timing shift from :00 → :17 to disambiguate.
#
# Pass criteria
#   etcd commit p99 stays < 100ms across the snapshot window  → snapshot is
#   probably NOT the meltdown trigger.
#
# Fail criteria
#   etcd commit p99 exceeds 500ms during the snapshot window → snapshot IS a
#   plausible meltdown trigger; mitigate by moving snapshot off the live CP
#   (etcd member API on a worker once HA lands), throttling, or relocating the
#   snapshot target to a faster disk.
#
# Safe under load: we do not modify the cluster; we only:
#   1. Read etcd stats via `talosctl etcd status` (read-only API call)
#   2. Query Mimir for commit-duration histogram (read-only)
#   3. Create a one-shot Job from the existing CronJob (`kubectl create job
#      --from=cronjob/etcd-backup`) — same snapshot the CronJob already runs
#      hourly, so cluster impact (if any) is exactly the impact you see at :17
#   4. Time `kubectl get nodes` repeatedly (read-only)
#   5. Clean up the one-shot Job afterward
#
# Cluster mid-meltdown? Do NOT run this. Wait until the cluster is stable for
# at least 15 min (cilium agents 5/5 Ready, no API timeouts), then run.
#
# Usage
#   ./scripts/test-suspect-etcd-snapshot.sh                      # default 60s window
#   PROBE_DURATION=180 ./scripts/test-suspect-etcd-snapshot.sh   # longer window
#   SKIP_TRIGGER=1   ./scripts/test-suspect-etcd-snapshot.sh     # passive: just measure for PROBE_DURATION, do not create snapshot
#   DRY_RUN=1        ./scripts/test-suspect-etcd-snapshot.sh     # print the plan, do nothing
#
# Output
#   stdout: human-readable banner + per-phase table
#   .output/etcd-snapshot-probe/<UTC-timestamp>/
#     ├── baseline.json         # 60s of pre-snapshot samples
#     ├── during.json           # samples taken while the Job runs
#     ├── after.json            # 60s of post-snapshot samples
#     ├── apiserver-latency.csv # ts,phase,seconds for `get nodes`
#     ├── job-events.log        # `kubectl describe job` once it finishes
#     └── summary.txt           # pass/fail verdict + numbers

set -uo pipefail # NOT -e: we want a final summary even on partial failures

# -------------- config ----------------
TALOS_NODE="${TALOS_NODE:-192.168.1.54}"
NAMESPACE="${NAMESPACE:-backup}"
CRONJOB_NAME="${CRONJOB_NAME:-etcd-backup}"
PROBE_DURATION="${PROBE_DURATION:-60}"                    # seconds per phase (baseline / after)
SAMPLE_INTERVAL="${SAMPLE_INTERVAL:-5}"                   # seconds between samples within a phase
APISERVER_PROBE_INTERVAL="${APISERVER_PROBE_INTERVAL:-2}" # seconds between `get nodes` probes
SKIP_TRIGGER="${SKIP_TRIGGER:-0}"
DRY_RUN="${DRY_RUN:-0}"

MIMIR_NAMESPACE="${MIMIR_NAMESPACE:-monitoring}"
MIMIR_SERVICE="${MIMIR_SERVICE:-mimir-query-frontend}"
MIMIR_PORT="${MIMIR_PORT:-8080}"
MIMIR_PATH="${MIMIR_PATH:-/prometheus/api/v1/query}"

PASS_THRESHOLD_MS="${PASS_THRESHOLD_MS:-100}" # p99 commit duration; below = healthy
FAIL_THRESHOLD_MS="${FAIL_THRESHOLD_MS:-500}" # p99 commit duration; above = snapshot is a trigger

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TS="$(date -u +%Y%m%dT%H%M%SZ)"
OUTDIR="${PROJECT_ROOT}/.output/etcd-snapshot-probe/${TS}"
mkdir -p "$OUTDIR"

TALOSCONFIG_FLAG="--talosconfig ${PROJECT_ROOT}/configs/talosconfig"

JOB_NAME="etcd-backup-probe-${TS,,}" # lowercase, k8s-safe
# fall back if zsh-style ${VAR,,} not supported (older bash):
if [[ "$JOB_NAME" == *"\${"* ]]; then
  JOB_NAME="etcd-backup-probe-$(echo "$TS" | tr '[:upper:]' '[:lower:]')"
fi

# -------------- colors ----------------
if [[ -t 1 ]]; then
  RED=$'\033[0;31m'
  GRN=$'\033[0;32m'
  YEL=$'\033[1;33m'
  BLU=$'\033[0;34m'
  CYN=$'\033[0;36m'
  DIM=$'\033[2m'
  NC=$'\033[0m'
else
  RED=""
  GRN=""
  YEL=""
  BLU=""
  CYN=""
  DIM=""
  NC=""
fi

# -------------- helpers ---------------
ts() { date -u +%Y-%m-%dT%H:%M:%SZ; }
ms_now() { python3 -c 'import time; print(int(time.time()*1000))'; }
info() { printf "${DIM}[%s]${NC} ${BLU}ℹ${NC}  %b\n" "$(ts)" "$*"; }
ok() { printf "${DIM}[%s]${NC} ${GRN}✓${NC}  %b\n" "$(ts)" "$*"; }
warn() { printf "${DIM}[%s]${NC} ${YEL}⚠${NC}  %b\n" "$(ts)" "$*"; }
err() { printf "${DIM}[%s]${NC} ${RED}✗${NC}  %b\n" "$(ts)" "$*" >&2; }
hr() { printf "${DIM}%s${NC}\n" "────────────────────────────────────────────────────────────────────"; }

require_cmd() {
  local c=$1
  if ! command -v "$c" > /dev/null 2>&1; then
    err "missing required command: $c"
    exit 2
  fi
}

# -------------- prereqs ---------------
require_cmd kubectl
require_cmd talosctl
require_cmd jq
require_cmd python3

if ! kubectl cluster-info > /dev/null 2>&1; then
  err "kubectl can't reach cluster; aborting"
  exit 2
fi

if ! kubectl -n "$NAMESPACE" get cronjob "$CRONJOB_NAME" > /dev/null 2>&1; then
  err "cronjob ${NAMESPACE}/${CRONJOB_NAME} not found; nothing to probe"
  exit 2
fi

# -------------- banner ----------------
cat << EOF
${CYN}┏━━━ etcd snapshot suspect probe ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓
┃ Hypothesis (TALOS-w4t): manual snapshot triggers fsync storm → apiserver
┃                         stalls → cilium /healthz fails → cascade.
┃ Counterhypothesis (TALOS-r10): Flux throttle is the real fix; snapshot is fine.
┃
┃ Target node     : ${TALOS_NODE}
┃ CronJob         : ${NAMESPACE}/${CRONJOB_NAME}
┃ Probe duration  : ${PROBE_DURATION}s baseline + during + ${PROBE_DURATION}s after
┃ Sample interval : every ${SAMPLE_INTERVAL}s (metrics), every ${APISERVER_PROBE_INTERVAL}s (apiserver)
┃ Mimir target    : ${MIMIR_SERVICE}.${MIMIR_NAMESPACE}.svc:${MIMIR_PORT}${MIMIR_PATH}
┃ Pass threshold  : etcd commit p99 < ${PASS_THRESHOLD_MS}ms
┃ Fail threshold  : etcd commit p99 > ${FAIL_THRESHOLD_MS}ms
┃ Output          : ${OUTDIR}
┃ Trigger mode    : $(if [[ "$SKIP_TRIGGER" == "1" ]]; then echo "PASSIVE (will NOT create snapshot)"; else echo "ACTIVE (will create one-shot Job)"; fi)
┃ Dry run         : $(if [[ "$DRY_RUN" == "1" ]]; then echo "YES (no-op)"; else echo "NO"; fi)
┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┛${NC}
EOF

if [[ "$DRY_RUN" == "1" ]]; then
  ok "dry run complete; nothing executed"
  exit 0
fi

# Helpful pre-flight: log the current cluster state so we know we ran from a healthy baseline
{
  echo "=== test run started $(ts) ==="
  echo "## cluster state pre-probe"
  kubectl get nodes -o wide 2>&1 || true
  echo
  echo "## cilium-agent pods"
  kubectl get pods -n kube-system -l k8s-app=cilium 2>&1 || true
  echo
  echo "## etcd status (talosctl)"
  # shellcheck disable=SC2086
  talosctl ${TALOSCONFIG_FLAG} --nodes "${TALOS_NODE}" etcd status 2>&1 || true
} > "${OUTDIR}/preflight.log"

# -------------- mimir query helper ----
# Runs a PromQL query against Mimir via in-cluster service. Falls back to
# null if the query fails or returns no data (e.g. etcd metrics not scraped).
# Output: JSON to stdout, exit 0 on success, exit 1 on error.
mimir_query() {
  local promql="$1"
  local result
  result=$(kubectl run -n "$MIMIR_NAMESPACE" "etcd-probe-$$-$(ms_now)" \
    --rm -i --restart=Never --quiet --timeout=15s \
    --image=curlimages/curl:8.10.1 -- \
    curl -sS --max-time 10 -G \
    --data-urlencode "query=${promql}" \
    "http://${MIMIR_SERVICE}.${MIMIR_NAMESPACE}.svc:${MIMIR_PORT}${MIMIR_PATH}" \
    2> /dev/null || true)
  if [[ -z "$result" ]]; then
    echo '{"status":"error","error":"empty response"}'
    return 1
  fi
  echo "$result"
}

# The standard etcd histogram for commit latency. If your cluster doesn't
# scrape etcd:2381 (Talos exposes it; you may need to add a scrape config),
# this query returns no data. Script handles that.
ETCD_P99_PROMQL='histogram_quantile(0.99, sum by (le) (rate(etcd_disk_backend_commit_duration_seconds_bucket[1m])))'
ETCD_P50_PROMQL='histogram_quantile(0.50, sum by (le) (rate(etcd_disk_backend_commit_duration_seconds_bucket[1m])))'
ETCD_FSYNC_P99_PROMQL='histogram_quantile(0.99, sum by (le) (rate(etcd_disk_wal_fsync_duration_seconds_bucket[1m])))'
ETCD_DB_SIZE_PROMQL='etcd_mvcc_db_total_size_in_bytes'

# Extract a single scalar value from a Prometheus instant query response, or
# print "null" if not available.
extract_scalar() {
  local json="$1"
  echo "$json" | jq -r '.data.result[0].value[1] // "null"' 2> /dev/null || echo "null"
}

# Take one full sample and append to a file (one JSON object per line).
sample_once() {
  local phase="$1"
  local outfile="$2"
  local sample_ts p99 p50 fsync_p99 db_size
  sample_ts=$(ts)

  local p99_raw p50_raw fsync_raw db_raw
  p99_raw=$(mimir_query "$ETCD_P99_PROMQL")
  p99=$(extract_scalar "$p99_raw")
  p50_raw=$(mimir_query "$ETCD_P50_PROMQL")
  p50=$(extract_scalar "$p50_raw")
  fsync_raw=$(mimir_query "$ETCD_FSYNC_P99_PROMQL")
  fsync_p99=$(extract_scalar "$fsync_raw")
  db_raw=$(mimir_query "$ETCD_DB_SIZE_PROMQL")
  db_size=$(extract_scalar "$db_raw")

  printf '{"ts":"%s","phase":"%s","commit_p99_s":"%s","commit_p50_s":"%s","fsync_p99_s":"%s","db_size_bytes":"%s"}\n' \
    "$sample_ts" "$phase" "$p99" "$p50" "$fsync_p99" "$db_size" >> "$outfile"

  # Also log the talosctl etcd status (read-only) — it returns dbSize, raftIndex etc.
  # shellcheck disable=SC2086
  talosctl ${TALOSCONFIG_FLAG} --nodes "${TALOS_NODE}" etcd status -o json \
    >> "${outfile%.json}.talosctl.jsonl" 2> /dev/null || true

  printf "%-8s %s  p99=%-12s p50=%-12s fsync_p99=%-12s db=%s\n" \
    "$phase" "$sample_ts" "$p99" "$p50" "$fsync_p99" "$db_size"
}

# Probe apiserver responsiveness in the background and log to CSV.
APISERVER_CSV="${OUTDIR}/apiserver-latency.csv"
echo "ts,phase,seconds,success" > "$APISERVER_CSV"

apiserver_probe_loop() {
  local phase="$1" duration_s="$2"
  local end=$(($(date +%s) + duration_s))
  while [[ $(date +%s) -lt $end ]]; do
    local start_ms end_ms latency rc
    start_ms=$(ms_now)
    if kubectl --request-timeout=10s get nodes > /dev/null 2>&1; then
      rc=true
    else
      rc=false
    fi
    end_ms=$(ms_now)
    latency=$(python3 -c "print(($end_ms - $start_ms) / 1000.0)")
    printf "%s,%s,%s,%s\n" "$(ts)" "$phase" "$latency" "$rc" >> "$APISERVER_CSV"
    sleep "$APISERVER_PROBE_INTERVAL"
  done
}

# -------------- phase 1: baseline ------
hr
info "PHASE 1 — baseline (${PROBE_DURATION}s, no snapshot)"
hr
apiserver_probe_loop "baseline" "$PROBE_DURATION" &
APISERVER_PID=$!
BASELINE_FILE="${OUTDIR}/baseline.json"
phase_end=$(($(date +%s) + PROBE_DURATION))
while [[ $(date +%s) -lt $phase_end ]]; do
  sample_once "baseline" "$BASELINE_FILE"
  sleep "$SAMPLE_INTERVAL"
done
wait "$APISERVER_PID" 2> /dev/null || true

# -------------- phase 2: trigger -------
hr
info "PHASE 2 — snapshot phase"
hr

if [[ "$SKIP_TRIGGER" == "1" ]]; then
  warn "SKIP_TRIGGER=1; not creating snapshot Job. Will just measure for ${PROBE_DURATION}s."
  DURING_FILE="${OUTDIR}/during.json"
  apiserver_probe_loop "during-skipped" "$PROBE_DURATION" &
  APISERVER_PID=$!
  phase_end=$(($(date +%s) + PROBE_DURATION))
  while [[ $(date +%s) -lt $phase_end ]]; do
    sample_once "during-skipped" "$DURING_FILE"
    sleep "$SAMPLE_INTERVAL"
  done
  wait "$APISERVER_PID" 2> /dev/null || true
else
  info "creating one-shot Job from cronjob/${CRONJOB_NAME}: ${JOB_NAME}"
  if ! kubectl -n "$NAMESPACE" create job "$JOB_NAME" --from="cronjob/${CRONJOB_NAME}" > /dev/null; then
    err "failed to create Job; aborting"
    exit 3
  fi
  ok "Job created"

  DURING_FILE="${OUTDIR}/during.json"
  apiserver_probe_loop "during" 600 & # apiserver probe runs until we kill it
  APISERVER_PID=$!

  # Sample every SAMPLE_INTERVAL until the Job reaches a terminal state
  # (Complete | Failed). Cap at 10 min for safety.
  job_start_epoch=$(date +%s)
  job_max=600
  while true; do
    sample_once "during" "$DURING_FILE"
    # Check job condition
    job_status=$(kubectl -n "$NAMESPACE" get job "$JOB_NAME" \
      -o jsonpath='{.status.conditions[?(@.status=="True")].type}' 2> /dev/null || echo "")
    if [[ "$job_status" == "Complete" ]] || [[ "$job_status" == "Failed" ]]; then
      ok "Job reached terminal state: ${job_status}"
      break
    fi
    if (($(date +%s) - job_start_epoch > job_max)); then
      warn "Job did not finish within ${job_max}s; moving on"
      break
    fi
    sleep "$SAMPLE_INTERVAL"
  done

  job_duration=$(($(date +%s) - job_start_epoch))
  info "snapshot Job ran for ~${job_duration}s"

  kill "$APISERVER_PID" 2> /dev/null || true
  wait "$APISERVER_PID" 2> /dev/null || true

  # Capture diagnostics from the Job before cleanup
  kubectl -n "$NAMESPACE" describe job "$JOB_NAME" > "${OUTDIR}/job-events.log" 2>&1 || true
  kubectl -n "$NAMESPACE" logs --all-containers --prefix \
    -l job-name="$JOB_NAME" --tail=200 > "${OUTDIR}/job-logs.log" 2>&1 || true
fi

# -------------- phase 3: after ---------
hr
info "PHASE 3 — recovery (${PROBE_DURATION}s, no snapshot)"
hr
apiserver_probe_loop "after" "$PROBE_DURATION" &
APISERVER_PID=$!
AFTER_FILE="${OUTDIR}/after.json"
phase_end=$(($(date +%s) + PROBE_DURATION))
while [[ $(date +%s) -lt $phase_end ]]; do
  sample_once "after" "$AFTER_FILE"
  sleep "$SAMPLE_INTERVAL"
done
wait "$APISERVER_PID" 2> /dev/null || true

# -------------- cleanup ---------------
if [[ "$SKIP_TRIGGER" != "1" ]]; then
  if kubectl -n "$NAMESPACE" get job "$JOB_NAME" > /dev/null 2>&1; then
    info "cleaning up one-shot Job ${JOB_NAME}"
    kubectl -n "$NAMESPACE" delete job "$JOB_NAME" --wait=false > /dev/null 2>&1 || true
  fi
fi

# -------------- summary ---------------
hr
info "computing verdict"
hr

# Compute max-of-p99 for each phase. "null" samples are filtered out;
# if EVERY sample was null, we cannot conclude → "UNKNOWN".
summarize_phase() {
  local file="$1"
  if [[ ! -s "$file" ]]; then
    echo "null null null"
    return
  fi
  # Output: max_p99_ms max_fsync_ms n_valid_samples
  python3 - "$file" << 'PY'
import json, sys
fp = sys.argv[1]
p99_vals = []
fsync_vals = []
n = 0
with open(fp) as f:
    for line in f:
        try:
            obj = json.loads(line)
        except Exception:
            continue
        n += 1
        for k, dest in (("commit_p99_s", p99_vals), ("fsync_p99_s", fsync_vals)):
            v = obj.get(k)
            if v is None or v == "null" or v == "NaN":
                continue
            try:
                dest.append(float(v))
            except ValueError:
                pass
def fmt(arr):
    if not arr:
        return "null"
    return f"{max(arr)*1000:.1f}"
print(f"{fmt(p99_vals)} {fmt(fsync_vals)} {n}")
PY
}

read -r BASE_P99 BASE_FSYNC BASE_N < <(summarize_phase "${OUTDIR}/baseline.json")
read -r DUR_P99 DUR_FSYNC DUR_N < <(summarize_phase "${OUTDIR}/during.json")
read -r AFT_P99 AFT_FSYNC AFT_N < <(summarize_phase "${OUTDIR}/after.json")

# Apiserver latency summary
if [[ -s "$APISERVER_CSV" ]]; then
  API_SUMMARY=$(
    python3 - "$APISERVER_CSV" << 'PY'
import csv, sys
rows = list(csv.DictReader(open(sys.argv[1])))
def stats(phase):
    vals = [float(r["seconds"]) for r in rows if r["phase"].startswith(phase) and r["success"]=="true"]
    fails = sum(1 for r in rows if r["phase"].startswith(phase) and r["success"]=="false")
    if not vals:
        return f"{phase}: no successful probes ({fails} failures)"
    return f"{phase}: n={len(vals)}, max={max(vals)*1000:.0f}ms, p95={sorted(vals)[int(0.95*len(vals))-1 if len(vals)>1 else 0]*1000:.0f}ms, fail={fails}"
print(stats("baseline"))
print(stats("during"))
print(stats("after"))
PY
  )
else
  API_SUMMARY="(no apiserver latency samples collected)"
fi

# Verdict
verdict_color=""
verdict_label=""
verdict_explanation=""

if [[ "$DUR_P99" == "null" ]]; then
  verdict_color="$YEL"
  verdict_label="UNKNOWN — etcd metrics not scraped"
  verdict_explanation="No samples returned data for etcd_disk_backend_commit_duration_seconds.
This usually means nothing is scraping etcd's metrics endpoint at :2381.
Talos exposes it (see configs/nodes/controlplane.yaml: listen-metrics-urls)
but the alloy scrape config in infrastructure/base/monitoring/v2-otel/alloy/
needs an explicit prometheus.scrape stanza for the CP node:2381. Add one,
re-run this probe.

Falling back to apiserver-latency signal:
${API_SUMMARY}

If 'during' shows >5x baseline apiserver latency or failure spikes, the
snapshot is at least correlated with apiserver pressure even without direct
etcd metrics."
elif python3 -c "import sys; sys.exit(0 if float('$DUR_P99') > $FAIL_THRESHOLD_MS else 1)"; then
  verdict_color="$RED"
  verdict_label="FAIL — etcd commit p99 exceeded ${FAIL_THRESHOLD_MS}ms during snapshot"
  verdict_explanation="Snapshot IS a plausible meltdown trigger. Confirms TALOS-w4t hypothesis.
Mitigations to consider in priority order:
  1. Move snapshot off the live CP after HA control plane (TALOS-arx)
     — use etcd member API against a worker etcd peer.
  2. Throttle snapshot frequency from hourly to 4h or 6h (it's a homelab).
  3. Add 'nice'-equivalent IO priority — Talos doesn't expose ionice but
     you can use a CronJob TZ to schedule during low-load hours.
  4. Move snapshot target to a faster disk (NVMe vs SATA) — current target
     is emptyDir on the CP filesystem before MinIO upload."
elif python3 -c "import sys; sys.exit(0 if float('$DUR_P99') < $PASS_THRESHOLD_MS else 1)"; then
  verdict_color="$GRN"
  verdict_label="PASS — etcd commit p99 stayed below ${PASS_THRESHOLD_MS}ms"
  verdict_explanation="Snapshot is NOT a meltdown trigger under current load. Refutes TALOS-w4t.
Real trigger is elsewhere — TALOS-r10 (Flux throttle) is the leading
candidate and was applied 2026-05-30. Keep observing."
else
  verdict_color="$YEL"
  verdict_label="WARNING — p99 between ${PASS_THRESHOLD_MS}ms and ${FAIL_THRESHOLD_MS}ms"
  verdict_explanation="Snapshot caused a measurable but not catastrophic spike. Could be a
contributor under high load even if not the sole trigger. Re-run during
peak workload to confirm."
fi

SUMMARY_FILE="${OUTDIR}/summary.txt"
{
  echo "=============================================================="
  echo " etcd snapshot suspect probe — summary"
  echo " run: ${TS}"
  echo "=============================================================="
  echo
  echo "Pass threshold (commit p99): < ${PASS_THRESHOLD_MS}ms"
  echo "Fail threshold (commit p99): > ${FAIL_THRESHOLD_MS}ms"
  echo
  printf "%-12s %-12s %-12s %-8s\n" "PHASE" "COMMIT_P99ms" "FSYNC_P99ms" "SAMPLES"
  printf "%-12s %-12s %-12s %-8s\n" "baseline" "$BASE_P99" "$BASE_FSYNC" "$BASE_N"
  printf "%-12s %-12s %-12s %-8s\n" "during" "$DUR_P99" "$DUR_FSYNC" "$DUR_N"
  printf "%-12s %-12s %-12s %-8s\n" "after" "$AFT_P99" "$AFT_FSYNC" "$AFT_N"
  echo
  echo "Apiserver responsiveness (kubectl get nodes):"
  echo "${API_SUMMARY}" | sed 's/^/  /'
  echo
  echo "VERDICT: ${verdict_label}"
  echo
  echo "${verdict_explanation}"
  echo
  echo "Artifacts: ${OUTDIR}/"
} | tee "$SUMMARY_FILE"

echo
printf "%sVERDICT: %s%s\n" "$verdict_color" "$verdict_label" "$NC"

# Exit code matches verdict for CI integration
if [[ "$verdict_label" == FAIL* ]]; then
  exit 1
elif [[ "$verdict_label" == PASS* ]]; then
  exit 0
else
  exit 2 # UNKNOWN / WARNING
fi
