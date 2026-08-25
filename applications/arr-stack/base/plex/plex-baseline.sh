#!/usr/bin/env bash
# Plex configuration baseline — apply on demand.
#
# WHAT / WHY
# A handful of Plex settings live in Preferences.xml on the config PVC, not in git (that file
# also holds the Plex token, machine identity and certs, so it must not be committed). If the
# config PVC is ever wiped and Plex regenerates a fresh config, these revert to defaults — most
# painfully HardwareAcceleratedCodecs turns OFF, which drops Plex to CPU/software transcoding and
# produces the bogus "your computer isn't powerful enough to stream" error even though the Intel
# GPU is right there in the pod.
#
# This script re-applies the baseline through Plex's own /:/prefs API — the only write path that
# persists correctly while PMS is running (editing Preferences.xml directly gets clobbered on
# shutdown). It is idempotent: re-running it only changes settings that drifted.
#
# WHEN TO RUN
#   - after a config-PVC wipe + fresh sign-in
#   - any time HW transcoding "turns itself off" or you're unsure the baseline is intact
#   - it is safe to run anytime; a correct setting is left untouched
#
# USAGE
#   ./plex-baseline.sh            # against the live pod in the cluster (uses kubectl)
#
# Requires: kubectl pointed at the cluster.

set -euo pipefail

NS="${PLEX_NS:-media}"
SELECTOR="${PLEX_SELECTOR:-app=plex}"

# ---- THE BASELINE — edit here. "key=value" per line. --------------------------------------
# HardwareAcceleratedCodecs=1            use the GPU (Intel QSV) for transcode  [needs Plex Pass]
# HardwareDevicePath=/dev/dri/renderD128 the Intel render node on talos02-gpu
# TranscoderTempDirectory=/transcode     the NVMe-backed emptyDir scratch, NOT the config PVC
DESIRED=$(cat <<'EOF'
HardwareAcceleratedCodecs=1
HardwareDevicePath=/dev/dri/renderD128
TranscoderTempDirectory=/transcode
EOF
)
# -------------------------------------------------------------------------------------------

pod=$(kubectl get pods -n "$NS" -l "$SELECTOR" --no-headers -o custom-columns=N:.metadata.name | head -1)
[ -n "$pod" ] || { echo "no Plex pod found in ns=$NS (selector $SELECTOR)"; exit 1; }
echo "Plex pod: $pod"

PREFS='/config/Library/Application Support/Plex Media Server/Preferences.xml'
tok=$(kubectl exec -n "$NS" "$pod" -c plex -- sh -c "sed -n 's/.*PlexOnlineToken=\"\([^\"]*\)\".*/\1/p' \"$PREFS\"" 2>/dev/null || true)
[ -n "$tok" ] || { echo "no Plex token yet — sign the server in first, then re-run"; exit 1; }

cur=$(kubectl exec -n "$NS" "$pod" -c plex -- sh -c "curl -sf 'http://127.0.0.1:32400/:/prefs?X-Plex-Token=$tok'" 2>/dev/null || true)
[ -n "$cur" ] || { echo "Plex API not answering — is the pod ready?"; exit 1; }

changed=0
while IFS='=' read -r key val; do
  [ -n "$key" ] || continue
  now=$(printf '%s' "$cur" | tr '<' '\n' | grep "id=\"$key\"" | sed -n 's/.*[^a-zA-Z]value="\([^"]*\)".*/\1/p' | head -1 || true)
  if [ "$now" = "$val" ]; then
    printf '  ✓ %-26s already %s\n' "$key" "$val"
    continue
  fi
  code=$(kubectl exec -n "$NS" "$pod" -c plex -- sh -c \
    "curl -s -o /dev/null -w '%{http_code}' -X PUT -G --data-urlencode '$key=$val' --data-urlencode 'X-Plex-Token=$tok' 'http://127.0.0.1:32400/:/prefs'" 2>/dev/null || echo "ERR")
  printf '  → %-26s %s -> %s -> HTTP %s\n' "$key" "${now:-<unset>}" "$val" "$code"
  changed=$((changed+1))
done <<< "$DESIRED"

echo "done ($changed changed)"
