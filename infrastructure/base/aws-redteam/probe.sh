#!/usr/bin/env bash
# ── Catalyst external red-team probe battery ─────────────────────────────────
# The framework's PLAYBOOK.md methodology, self-contained. Run from a GENUINE
# off-net host (an AWS EC2 box) — NOT the LAN and NOT the gluetun VPN, both of
# which NAT-hairpin to the same home WAN IP and cannot see what a real attacker
# sees (see pentest evidence/external_pass_notes.txt, the deferred cold pass).
#
# Canonical source. redteam-auto.yaml embeds this verbatim in its cloud-init;
# keep the two identical. Reuses talos-ingress config: rate_limit 10, framework UA.
#
# Non-destructive: read-only probes only. ROE: pentest/target-packages/talos-ingress/scope.md.
set -u
UA="Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) pentest/talos-ingress"
C() { curl -sk --max-time 12 -A "$UA" "$@"; } # one probe at a time, ~sub-10/s
SELF_IP="$(C https://api.ipify.org || echo unknown)"
ORIGIN="$(dig +short origin.amberdark.net 2> /dev/null | tail -1)"
[ -z "$ORIGIN" ] && ORIGIN="108.64.138.156" # fallback; config says confirm at phase 0

code() { C -o /dev/null -w '%{http_code}' "$@"; }
sz() { C -o /dev/null -w '%{size_download}' "$@"; }

{
  echo "EXTERNAL VANTAGE CONFIRMATION — $(date -u +%FT%TZ), AWS EC2 egress ${SELF_IP} (genuine off-net)"
  echo "ORIGIN ${ORIGIN}  (dig origin.amberdark.net)"
  echo "--- reachability of the WAN entrypoints ---"
  echo "  :80  root  -> $(code -H 'Host: whoami.talos00' "http://${ORIGIN}/")"
  echo "  :443 root  -> $(code -H 'Host: whoami.talos00' "https://${ORIGIN}/")"
  echo "--- 001 Traefik dashboard / api@internal (unauth on :80) ---"
  echo "  /dashboard/  -> $(code -H 'Host: traefik.talos00' "http://${ORIGIN}/dashboard/")"
  echo "  /api/rawdata -> $(code -H 'Host: traefik.talos00' "http://${ORIGIN}/api/rawdata") ($(sz -H 'Host: traefik.talos00' "http://${ORIGIN}/api/rawdata") bytes)"
  echo "--- 006 origin host-spoof of internal admin UIs ---"
  for h in grafana argocd minio rabbitmq; do
    echo "  ${h}.talos00 :443 -> $(code -H "Host: ${h}.talos00" "https://${ORIGIN}/")"
  done
  echo "--- 005 arr /api carve-outs (priority-100, no lan-only) ---"
  echo "  qbittorrent /api/v2/app/preferences :443 -> $(code -H 'Host: qbittorrent.talos00' "https://${ORIGIN}/api/v2/app/preferences")"
  echo "  qbittorrent /api/v2/torrents/info   :80  -> $(code -H 'Host: qbittorrent.talos00' "http://${ORIGIN}/api/v2/torrents/info")"
  for h in sonarr radarr prowlarr tautulli; do
    echo "  ${h}.talos00 /api :443 -> $(code -H "Host: ${h}.talos00" "https://${ORIGIN}/api/v3/health") (control: 401=app-key enforced)"
  done
  echo "--- 002 Frigate forward-auth header bypass ---"
  echo "  frigate /api/config +forged X-authentik-username -> $(code -H 'Host: frigate.talos00' -H 'X-authentik-username: admin' "https://${ORIGIN}/api/config")"
  echo "--- 012 catalyst-nav manifest disclosure (fixed 2026-09-26) ---"
  echo "  /catalyst/resources/catalyst-nav.json -> $(code -H 'Host: forge.knowledgedump.space' "https://${ORIGIN}/catalyst/resources/catalyst-nav.json") (expect NOT 200)"
  echo "--- 007 public route through Cloudflare (control) ---"
  echo "  zipline.amberdark.net -> $(code https://zipline.amberdark.net/)"
  echo "PROBE DONE — $(date -u +%FT%TZ)"
} 2>&1
