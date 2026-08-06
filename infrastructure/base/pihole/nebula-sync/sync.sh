#!/bin/sh
# Pi-hole config sync — FOLLOWS THE ACTIVE PRIMARY.
#
# ⚠️ "nebula-sync" = Pi-hole config sync (v6 Teleporter). NOT related to "Nebula" the
# Slack mesh-VPN / its "lighthouse" nodes — unrelated project, name collision only.
#
# Loops every $SYNC_INTERVAL: find the active pod (Cilium L2-lease holder), back up its
# config via the v6 Teleporter API, restore to the idle standbys → UI/config changes made
# via the single VIP propagate; standbys stay failover-ready. Restores only ever hit idle
# pods (active is skipped) → no DNS impact. Carries pihole.toml + gravity.db, NOT stats.
#
# Loaded from a ConfigMap (kustomize configMapGenerator) — keeps the manifest free of code.
# NOTE ON $VARS: this file is embedded into a ConfigMap that Flux postBuild envsubst scans;
# envsubst only rewrites ${...} tokens, so we use BARE $VAR everywhere (read at runtime from
# the container env). Never use ${VAR} here or Flux will eat it before the shell sees it.
#
# METRICS: this loop emits Prometheus exposition text to $METRICS_FILE on a shared emptyDir.
# A sibling busybox-httpd container serves that file at :9092/metrics; the nebula-sync
# PodMonitor (podmonitor.yaml) scrapes it into Mimir via Alloy. We write here (no server in
# THIS container) so the sync image stays minimal. Counters are process-lifetime cumulative
# (reset on pod restart = a normal Prometheus counter reset). See the pihole dashboard's
# "Config Sync (nebula-sync)" row + the "nebula-sync run" annotation.
set -u

# This kubectl build doesn't auto-detect in-cluster config, so point it at the in-cluster
# API and read the SA token from its file (tokenFile → no token on argv; survives rotation).
printf 'apiVersion: v1\nkind: Config\nclusters:\n- name: c\n  cluster:\n    server: https://%s:%s\n    certificate-authority: /var/run/secrets/kubernetes.io/serviceaccount/ca.crt\ncontexts:\n- name: c\n  context:\n    cluster: c\n    user: u\ncurrent-context: c\nusers:\n- name: u\n  user:\n    tokenFile: /var/run/secrets/kubernetes.io/serviceaccount/token\n' \
  "$KUBERNETES_SERVICE_HOST" "$KUBERNETES_SERVICE_PORT" > /tmp/kubeconfig
export KUBECONFIG=/tmp/kubeconfig
KUBECTL="kubectl --request-timeout=10s"

# --- metrics state (Prometheus exposition, served by the busybox sidecar) --------------
METRICS_FILE=/metrics/metrics # shared emptyDir mount; sidecar httpd docroot serves /metrics
RUNS_SUCCESS=0                # cumulative: cycles that restored ALL standbys cleanly
RUNS_FAILURE=0                # cumulative: cycles that skipped or had ANY restore failure
LAST_SUCCESS_TS=0             # unix time of last fully-clean cycle (drives "Last sync age")
LAST_RUN_TS=0                 # unix time of last cycle of ANY result
LAST_DURATION=0               # wall-seconds of the last cycle
LAST_SYNCED=0                 # standbys restored OK in the last cycle
LAST_FAILED=0                 # standbys that failed restore in the last cycle (0 = healthy)

write_metrics() {
  # atomic rewrite (temp + mv on the same fs) so a scrape never reads a half-written file
  {
    printf '# HELP nebula_sync_runs_total Completed sync cycles by result.\n'
    printf '# TYPE nebula_sync_runs_total counter\n'
    printf 'nebula_sync_runs_total{result="success"} %s\n' "$RUNS_SUCCESS"
    printf 'nebula_sync_runs_total{result="failure"} %s\n' "$RUNS_FAILURE"
    printf '# HELP nebula_sync_last_success_timestamp_seconds Unix time of the last fully-clean sync.\n'
    printf '# TYPE nebula_sync_last_success_timestamp_seconds gauge\n'
    printf 'nebula_sync_last_success_timestamp_seconds %s\n' "$LAST_SUCCESS_TS"
    printf '# HELP nebula_sync_last_run_timestamp_seconds Unix time of the last sync attempt (any result).\n'
    printf '# TYPE nebula_sync_last_run_timestamp_seconds gauge\n'
    printf 'nebula_sync_last_run_timestamp_seconds %s\n' "$LAST_RUN_TS"
    printf '# HELP nebula_sync_duration_seconds Wall-clock duration of the last sync cycle.\n'
    printf '# TYPE nebula_sync_duration_seconds gauge\n'
    printf 'nebula_sync_duration_seconds %s\n' "$LAST_DURATION"
    printf '# HELP nebula_sync_replicas_synced Standby replicas restored OK in the last cycle.\n'
    printf '# TYPE nebula_sync_replicas_synced gauge\n'
    printf 'nebula_sync_replicas_synced %s\n' "$LAST_SYNCED"
    printf '# HELP nebula_sync_replicas_failed Standby replicas that failed restore in the last cycle.\n'
    printf '# TYPE nebula_sync_replicas_failed gauge\n'
    printf 'nebula_sync_replicas_failed %s\n' "$LAST_FAILED"
  } > "$METRICS_FILE.tmp" 2> /dev/null && mv "$METRICS_FILE.tmp" "$METRICS_FILE" 2> /dev/null
}

# record a finished cycle and refresh the metrics file. args: RESULT SYNCED FAILED
# RESULT=success bumps the success counter + advances LAST_SUCCESS_TS; anything else is a
# failure (skip / auth fail / partial restore). LAST_DURATION is set by the caller.
record() {
  LAST_RUN_TS=$(date +%s)
  LAST_SYNCED=$2
  LAST_FAILED=$3
  if [ "$1" = success ]; then
    RUNS_SUCCESS=$((RUNS_SUCCESS + 1))
    LAST_SUCCESS_TS=$LAST_RUN_TS
  else
    RUNS_FAILURE=$((RUNS_FAILURE + 1))
  fi
  write_metrics
}

# password via stdin (never on the curl argv / process list)
auth() {
  printf '{"password":"%s"}' "$PIHOLE_PASSWORD" |
    curl -s --max-time 10 -X POST "http://$1/api/auth" -H 'Content-Type: application/json' --data @- |
    sed -n 's/.*"sid":"\([^"]*\)".*/\1/p'
}

# only real StatefulSet pihole pods (excludes THIS worker + anything else)
PSEL='app=pihole,statefulset.kubernetes.io/pod-name'

sync_once() {
  START=$(date +%s)
  NODE=$($KUBECTL get lease cilium-l2announce-pihole-pihole -n kube-system -o jsonpath='{.spec.holderIdentity}' 2> /dev/null)
  [ -n "$NODE" ] || {
    echo "no L2 lease holder yet; skip"
    LAST_DURATION=$(($(date +%s) - START))
    record failure 0 0
    return 0
  }
  ACTIVE_IP=$($KUBECTL get pods -n pihole -l "$PSEL" --field-selector spec.nodeName="$NODE" -o jsonpath='{.items[0].status.podIP}' 2> /dev/null)
  ACTIVE_POD=$($KUBECTL get pods -n pihole -l "$PSEL" --field-selector spec.nodeName="$NODE" -o jsonpath='{.items[0].metadata.name}' 2> /dev/null)
  [ -n "$ACTIVE_IP" ] || {
    echo "cannot resolve active pod on $NODE; skip"
    LAST_DURATION=$(($(date +%s) - START))
    record failure 0 0
    return 0
  }
  SID=$(auth "$ACTIVE_IP")
  [ -n "$SID" ] || {
    echo "auth to active $ACTIVE_POD failed; skip"
    LAST_DURATION=$(($(date +%s) - START))
    record failure 0 0
    return 0
  }
  curl -s --max-time 20 -o /tmp/tele.zip -H "X-FTL-SID: $SID" "http://$ACTIVE_IP/api/teleporter"
  SZ=$(wc -c < /tmp/tele.zip 2> /dev/null || echo 0)
  [ "$SZ" -gt 100 ] || {
    echo "backup too small ($SZ); skip"
    LAST_DURATION=$(($(date +%s) - START))
    record failure 0 0
    return 0
  }
  # heartbeat: a healthy cycle reached the active primary + got its config. Liveness tracks
  # loop-alive, NOT per-replica restore success.
  date +%s > /tmp/last-sync
  OK=0
  FAIL=0
  for IP in $($KUBECTL get pods -n pihole -l "$PSEL" -o jsonpath='{range .items[*]}{.status.podIP}{"\n"}{end}' 2> /dev/null); do
    { [ -z "$IP" ] || [ "$IP" = "$ACTIVE_IP" ]; } && continue
    RSID=$(auth "$IP")
    [ -n "$RSID" ] || {
      echo "  $IP auth failed"
      FAIL=$((FAIL + 1))
      continue
    }
    CODE=$(curl -s --max-time 20 -o /dev/null -w '%{http_code}' -X POST -H "X-FTL-SID: $RSID" -F "file=@/tmp/tele.zip" "http://$IP/api/teleporter")
    [ "$CODE" = "200" ] && OK=$((OK + 1)) || {
      echo "  $IP restore HTTP=$CODE"
      FAIL=$((FAIL + 1))
    }
  done
  echo "$(date -u +%FT%TZ) primary=$ACTIVE_POD synced=$OK failed=$FAIL"
  # a cycle counts as success only if every standby restore returned 200; a partial failure
  # advances LAST_RUN_TS but NOT LAST_SUCCESS_TS, so "Last sync age" climbs until it clears.
  LAST_DURATION=$(($(date +%s) - START))
  if [ "$FAIL" -eq 0 ]; then
    record success "$OK" "$FAIL"
  else
    record failure "$OK" "$FAIL"
  fi
}

echo "nebula-sync worker starting (interval $SYNC_INTERVAL s)"
date +%s > /tmp/last-sync
# seed the success/run timestamps to boot time so "Last sync age" reads ~0 (not time()-0 =
# billions) until the first real cycle lands — mirrors the /tmp/last-sync heartbeat seed.
LAST_SUCCESS_TS=$(date +%s)
LAST_RUN_TS=$LAST_SUCCESS_TS
write_metrics # seed so the endpoint is scrapable before the first cycle finishes
while true; do
  sync_once
  sleep "$SYNC_INTERVAL"
done
