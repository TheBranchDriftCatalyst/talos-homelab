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
#   scripts/gpu-tunnel.sh                                       # the armed LLM rig
#   ROLE=image scripts/gpu-tunnel.sh                            # the armed image rig
#   NAME=inference-node-235b REGION=us-east-2 scripts/gpu-tunnel.sh   # one by name
#   LOCAL_PORT=18012 REMOTE_PORT=8012 scripts/gpu-tunnel.sh     # explicit ports
#
# Ports and the rig to target are DERIVED from the colocated table
# infrastructure/base/aws/apps/gpu-profiles.yaml, not hardcoded here — that port
# number used to live in four places across two repos. Env vars still override for
# ad-hoc use. The table's `endpoint.llmLocalPort` is 18000 and not 8000 because on
# this Mac :8000 is fchat-bouncer's uvicorn and :8012 is mac-sdlc-node's comfyui-shim.
#
# With no NAME given, this targets whichever rig of $ROLE (llm | image) is ARMED — i.e.
# has an uncommented claim line in aws/apps/kustomization.yaml, per
# scripts/lib/armed-rigs.rb. If none is — the default, deliberately — it says so and
# exits rather than polling forever for a box nobody asked for.
#
# ROLE exists because a token box and a pixel box are both `kind: XGPUInstance` and
# serve different ports; the claim's catalyst.io/gpu-role label is what separates them.
#
# Prereq: session-manager-plugin (brew install --cask session-manager-plugin).
set -uo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PROFILES="${PROFILES:-$REPO_ROOT/infrastructure/base/aws/apps/gpu-profiles.yaml}"
APPS_DIR="$REPO_ROOT/infrastructure/base/aws/apps"
ROLE="${ROLE:-llm}"

# ruby ships with macOS and has YAML in stdlib; same approach as check-spot-avail.sh.
prof() { ruby -ryaml -e "$1" "$PROFILES" 2> /dev/null; }

if [ -r "$PROFILES" ] && command -v ruby > /dev/null 2>&1; then
  # Ports are per-ROLE: the LLM rig serves vLLM on 8000, the image rig serves the
  # comfyui-shim on 8012. Picking the wrong pair tunnels successfully to a port with
  # nothing on it, which looks like a dead box rather than a wrong flag.
  if [ "$ROLE" = image ]; then
    : "${LOCAL_PORT:=$(prof 'puts YAML.load_file(ARGV[0]).dig("endpoint","imageLocalPort")')}"
    : "${REMOTE_PORT:=$(prof 'puts YAML.load_file(ARGV[0]).dig("endpoint","imageRemotePort")')}"
  else
    : "${LOCAL_PORT:=$(prof 'puts YAML.load_file(ARGV[0]).dig("endpoint","llmLocalPort")')}"
    : "${REMOTE_PORT:=$(prof 'puts YAML.load_file(ARGV[0]).dig("endpoint","llmRemotePort")')}"
  fi
  if [ -z "${NAME:-}" ]; then
    # The ARMED rig, derived from the kustomization — never from a `rigs[].state` field.
    # This read a `state` key that TALOS-cmni deleted, so it resolved to "" every time
    # and this script could not target a rig by table at all. No pipe on the capture:
    # the helper ABORTS on a malformed armed claim and `|| exit` must see that.
    ARMED=$("$REPO_ROOT/scripts/lib/armed-rigs.rb" "$APPS_DIR" "$ROLE") || exit 1
    NAME=$(printf '%s\n' "$ARMED" | head -1)
    if [ -z "$NAME" ]; then
      echo "No $ROLE rig is armed in aws/apps/kustomization.yaml." >&2
      echo "That is the default and it is deliberate — nothing is meant to be running." >&2
      echo "Turn one on by uncommenting its claim line there," >&2
      echo "or target one explicitly: NAME=<rig> $0" >&2
      exit 1
    fi
    REGION="${REGION:-$(prof "r=(YAML.load_file(ARGV[0])[\"rigs\"]||[]).find { |x| x[\"name\"] == \"$NAME\" }; print r ? r[\"region\"] : \"\"")}"
  fi
else
  echo "WARN: $PROFILES unreadable or ruby missing — using built-in defaults" >&2
fi

NAME="${NAME:-inference-node}"
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
