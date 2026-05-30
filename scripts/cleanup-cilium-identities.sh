#!/usr/bin/env bash
#
# One-shot cleanup of stale CiliumIdentity CRDs.
#
# Why: 2026-05-30 root-cause analysis (TALOS-yyt) — Cilium accumulated 19,439
# CiliumIdentity objects for only 180 live CiliumEndpoints. Each cilium-agent
# restart did a LIST returning ~30MB / 9438 objects which saturated etcd
# (apply request took >100ms), causing apiserver Handler timeouts, KubePrism
# EOFs, and the week-long meltdown cascade. cilium-operator's built-in
# identity GC runs every 15m but the operator itself was crashlooping on the
# same cascade, so GC never completed.
#
# What this does: finds CiliumIdentity CRDs not referenced by any live
# CiliumEndpoint and deletes them in safe batches. Companion to the Flux
# values change in infrastructure/base/cilium/values.yaml that adds a label
# filter to stop NEW pollution.
#
# Safety: only deletes identities NOT in use. If a pod comes up after we
# compute the in-use set but before we delete, Cilium will recreate the
# identity on demand — no policy disruption.
#
# Usage:
#   ./scripts/cleanup-cilium-identities.sh             # interactive
#   ./scripts/cleanup-cilium-identities.sh --yes       # skip confirmation
#   ./scripts/cleanup-cilium-identities.sh --dry-run   # plan only

set -euo pipefail

BATCH_SIZE="${BATCH_SIZE:-200}"
SLEEP_BETWEEN_BATCHES="${SLEEP_BETWEEN_BATCHES:-0}"
PARALLELISM="${PARALLELISM:-8}"

ASSUME_YES=false
DRY_RUN=false
for arg in "$@"; do
  case "$arg" in
    --yes | -y) ASSUME_YES=true ;;
    --dry-run | -n) DRY_RUN=true ;;
    *)
      echo "Unknown flag: $arg" >&2
      exit 1
      ;;
  esac
done

echo "==> Collecting in-use CiliumEndpoint identities"
USED_IDS_FILE=$(mktemp)
trap 'rm -f "$USED_IDS_FILE" "$ALL_IDS_FILE" "$UNUSED_IDS_FILE"' EXIT
kubectl get ciliumendpoints -A -o json |
  jq -r '.items[].status.identity.id // empty' |
  sort -u > "$USED_IDS_FILE"
USED_COUNT=$(wc -l < "$USED_IDS_FILE" | tr -d ' ')
echo "    in-use identities: $USED_COUNT"

echo "==> Collecting all CiliumIdentity CRDs"
ALL_IDS_FILE=$(mktemp)
kubectl get ciliumidentities -o jsonpath='{range .items[*]}{.metadata.name}{"\n"}{end}' |
  sort -u > "$ALL_IDS_FILE"
ALL_COUNT=$(wc -l < "$ALL_IDS_FILE" | tr -d ' ')
echo "    total identities: $ALL_COUNT"

UNUSED_IDS_FILE=$(mktemp)
comm -23 "$ALL_IDS_FILE" "$USED_IDS_FILE" > "$UNUSED_IDS_FILE"
UNUSED_COUNT=$(wc -l < "$UNUSED_IDS_FILE" | tr -d ' ')

echo
echo "==> Plan"
echo "    keep:   $USED_COUNT identities (currently referenced by CiliumEndpoints)"
echo "    delete: $UNUSED_COUNT identities (stale — no live endpoint)"
echo "    batch:  $BATCH_SIZE per kubectl call, ${SLEEP_BETWEEN_BATCHES}s between"
echo

if [ "$UNUSED_COUNT" -eq 0 ]; then
  echo "Nothing to delete. Exiting."
  exit 0
fi

if [ "$DRY_RUN" = true ]; then
  echo "Dry-run only. First 10 IDs that would be deleted:"
  head -10 "$UNUSED_IDS_FILE" | sed 's/^/    /'
  exit 0
fi

if [ "$ASSUME_YES" != true ]; then
  read -p "Proceed with deletion? [y/N] " -n 1 -r REPLY
  echo
  [[ "$REPLY" =~ ^[Yy]$ ]] || {
    echo "Aborted."
    exit 0
  }
fi

echo "==> Deleting (parallelism=$PARALLELISM, batch=$BATCH_SIZE)"
# WITHOUT -I {} — that flag forces -n=1 (one arg per invocation). With just
# -n $BATCH_SIZE -P $PARALLELISM, xargs runs $PARALLELISM concurrent kubectl
# calls, each appending $BATCH_SIZE IDs to the command line.
xargs -n "$BATCH_SIZE" -P "$PARALLELISM" \
  kubectl delete ciliumidentity --ignore-not-found=true \
  < "$UNUSED_IDS_FILE" > /dev/null 2>&1 &
DELETE_PID=$!

# progress poll loop while xargs runs
while kill -0 "$DELETE_PID" 2> /dev/null; do
  REMAINING=$(kubectl get ciliumidentities --no-headers 2> /dev/null | wc -l | tr -d ' ')
  printf "\r    remaining: %d (target: ~%d)" "$REMAINING" "$USED_COUNT"
  sleep 3
done
wait "$DELETE_PID"
echo

echo
echo "==> Done — verify with: kubectl get ciliumidentities | wc -l"
echo
echo "Verify with: kubectl get ciliumidentities | wc -l"
echo "Watch cilium-agent restart count stabilize: kubectl get pods -n kube-system -l k8s-app=cilium"
