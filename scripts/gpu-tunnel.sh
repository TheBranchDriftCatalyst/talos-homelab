#!/usr/bin/env bash
# gpu-tunnel.sh — SSM port-forward from this Mac to an XGPUInstance's vLLM port,
# with automatic reconnect.
#
# Every XGPUInstance SG is EGRESS-ONLY (no inbound rules at all), so Session
# Manager is the ONLY way to reach the box. There is no public inference port.
#
# WHY IT LOOPS AND RE-RESOLVES: the instance id is not stable.
#   * spot interruption -> Crossplane recreates the Instance -> new id
#   * gpu-testrig-reaper (age > 6h, poc-demo label) deletes the XR, Flux puts it
#     straight back -> new id
# A tunnel pinned to one id dies at the first churn and takes local chat with it.
# Re-resolving by the Name tag on every attempt survives both.
#
# Usage:
#   scripts/gpu-tunnel.sh                                    # little boi defaults
#   NAME=gpu-node-235b REGION=us-east-2 scripts/gpu-tunnel.sh   # big boi
#   LOCAL_PORT=18012 REMOTE_PORT=8012 scripts/gpu-tunnel.sh     # the ComfyUI shim
#
# Ports and the rig to target are DERIVED from the colocated table
# infrastructure/base/aws/apps/gpu-profiles.yaml, not hardcoded here — that port
# number used to live in four places across two repos. Env vars still override for
# ad-hoc use. The table's `endpoint.llmLocalPort` is 18000 and not 8000 because on
# this Mac :8000 is fchat-bouncer's uvicorn and :8012 is mac-sdlc-node's comfyui-shim.
#
# With no NAME given, this targets whichever rig the table marks state: "on". If none
# is on — the default, deliberately — it says so and exits rather than polling forever
# for a box nobody asked for.
#
# Prereq: session-manager-plugin (brew install --cask session-manager-plugin).
set -uo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PROFILES="${PROFILES:-$REPO_ROOT/infrastructure/base/aws/apps/gpu-profiles.yaml}"

# ruby ships with macOS and has YAML in stdlib; same approach as check-spot-avail.sh.
prof() { ruby -ryaml -e "$1" "$PROFILES" 2> /dev/null; }

if [ -r "$PROFILES" ] && command -v ruby > /dev/null 2>&1; then
  : "${LOCAL_PORT:=$(prof 'puts YAML.load_file(ARGV[0]).dig("endpoint","llmLocalPort")')}"
  : "${REMOTE_PORT:=$(prof 'puts YAML.load_file(ARGV[0]).dig("endpoint","llmRemotePort")')}"
  if [ -z "${NAME:-}" ]; then
    NAME=$(prof 'r=(YAML.load_file(ARGV[0])["rigs"]||[]).find { |x| x["state"].to_s == "on" }; print r ? r["name"] : ""')
    if [ -z "$NAME" ]; then
      echo "No rig is marked state: \"on\" in $PROFILES." >&2
      echo "That is the default and it is deliberate — nothing is meant to be running." >&2
      echo "Turn one on by uncommenting its line in infrastructure/base/aws/apps/kustomization.yaml," >&2
      echo "or target one explicitly: NAME=gpu-node-27b-fp8 $0" >&2
      exit 1
    fi
    REGION="${REGION:-$(prof "r=(YAML.load_file(ARGV[0])[\"rigs\"]||[]).find { |x| x[\"name\"] == \"$NAME\" }; print r ? r[\"region\"] : \"\"")}"
  fi
else
  echo "WARN: $PROFILES unreadable or ruby missing — using built-in defaults" >&2
fi

NAME="${NAME:-gpu-node-27b-fp8}"
REGION="${REGION:-us-east-2}"
LOCAL_PORT="${LOCAL_PORT:-18000}"
REMOTE_PORT="${REMOTE_PORT:-8000}"
RETRY_SECS="${RETRY_SECS:-15}"

if ! command -v session-manager-plugin > /dev/null 2>&1; then
  echo "FATAL: session-manager-plugin not installed." >&2
  echo "       brew install --cask session-manager-plugin" >&2
  exit 1
fi

if lsof -nP -iTCP:"$LOCAL_PORT" -sTCP:LISTEN > /dev/null 2>&1; then
  echo "FATAL: local port $LOCAL_PORT is already in use:" >&2
  lsof -nP -iTCP:"$LOCAL_PORT" -sTCP:LISTEN >&2
  echo "       pick another with LOCAL_PORT=..." >&2
  exit 1
fi

echo "tunnel: localhost:$LOCAL_PORT -> $NAME:$REMOTE_PORT ($REGION)"
echo "        re-resolves the instance id each attempt; Ctrl-C to stop."

trap 'echo; echo "tunnel: stopped."; exit 0' INT TERM

while true; do
  ID=$(aws ec2 describe-instances --region "$REGION" \
    --filters "Name=tag:Name,Values=$NAME" "Name=instance-state-name,Values=running" \
    --query 'Reservations[].Instances[0].InstanceId' --output text 2> /dev/null)

  if [ -z "$ID" ] || [ "$ID" = "None" ]; then
    echo "$(date '+%H:%M:%S')  no RUNNING instance tagged Name=$NAME in $REGION — retrying in ${RETRY_SECS}s"
    echo "            (is the claim uncommented in aws/apps/kustomization.yaml? spot capacity?)"
    sleep "$RETRY_SECS"
    continue
  fi

  echo "$(date '+%H:%M:%S')  connecting to $ID …"
  # Blocks until the session drops. A clean Ctrl-C is caught by the trap above.
  aws ssm start-session --region "$REGION" --target "$ID" \
    --document-name AWS-StartPortForwardingSession \
    --parameters "portNumber=$REMOTE_PORT,localPortNumber=$LOCAL_PORT"

  echo "$(date '+%H:%M:%S')  session to $ID ended — re-resolving in ${RETRY_SECS}s"
  sleep "$RETRY_SECS"
done
