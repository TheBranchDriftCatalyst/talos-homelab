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
set -u

# This kubectl build doesn't auto-detect in-cluster config, so point it at the in-cluster
# API and read the SA token from its file (tokenFile → no token on argv; survives rotation).
printf 'apiVersion: v1\nkind: Config\nclusters:\n- name: c\n  cluster:\n    server: https://%s:%s\n    certificate-authority: /var/run/secrets/kubernetes.io/serviceaccount/ca.crt\ncontexts:\n- name: c\n  context:\n    cluster: c\n    user: u\ncurrent-context: c\nusers:\n- name: u\n  user:\n    tokenFile: /var/run/secrets/kubernetes.io/serviceaccount/token\n' \
  "$KUBERNETES_SERVICE_HOST" "$KUBERNETES_SERVICE_PORT" > /tmp/kubeconfig
export KUBECONFIG=/tmp/kubeconfig
KUBECTL="kubectl --request-timeout=10s"

# password via stdin (never on the curl argv / process list)
auth() {
  printf '{"password":"%s"}' "$PIHOLE_PASSWORD" |
    curl -s --max-time 10 -X POST "http://$1/api/auth" -H 'Content-Type: application/json' --data @- |
    sed -n 's/.*"sid":"\([^"]*\)".*/\1/p'
}

# only real StatefulSet pihole pods (excludes THIS worker + anything else)
PSEL='app=pihole,statefulset.kubernetes.io/pod-name'

sync_once() {
  NODE=$($KUBECTL get lease cilium-l2announce-pihole-pihole -n kube-system -o jsonpath='{.spec.holderIdentity}' 2> /dev/null)
  [ -n "$NODE" ] || {
    echo "no L2 lease holder yet; skip"
    return 0
  }
  ACTIVE_IP=$($KUBECTL get pods -n pihole -l "$PSEL" --field-selector spec.nodeName="$NODE" -o jsonpath='{.items[0].status.podIP}' 2> /dev/null)
  ACTIVE_POD=$($KUBECTL get pods -n pihole -l "$PSEL" --field-selector spec.nodeName="$NODE" -o jsonpath='{.items[0].metadata.name}' 2> /dev/null)
  [ -n "$ACTIVE_IP" ] || {
    echo "cannot resolve active pod on $NODE; skip"
    return 0
  }
  SID=$(auth "$ACTIVE_IP")
  [ -n "$SID" ] || {
    echo "auth to active $ACTIVE_POD failed; skip"
    return 0
  }
  curl -s --max-time 20 -o /tmp/tele.zip -H "X-FTL-SID: $SID" "http://$ACTIVE_IP/api/teleporter"
  SZ=$(wc -c < /tmp/tele.zip 2> /dev/null || echo 0)
  [ "$SZ" -gt 100 ] || {
    echo "backup too small ($SZ); skip"
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
}

echo "nebula-sync worker starting (interval $SYNC_INTERVAL s)"
date +%s > /tmp/last-sync
while true; do
  sync_once
  sleep "$SYNC_INTERVAL"
done
