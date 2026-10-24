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
# HOST LISTS below (TALOS_HOSTS / KD_HOSTS) are a POINT-IN-TIME snapshot generated
# from the live IngressRoute set on 2026-10-24. Regenerate before a run:
#   kubectl get ingressroute -A -o json | <extract Host(`*.talos00`) and *.knowledgedump.space>
# A host added to the cluster after that date is NOT covered until the lists are refreshed.
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

TALOS_HOSTS="apps.homepage.talos00 \
    argocd.talos00 \
    arrs.homepage.talos00 \
    audiobookshelf.talos00 \
    auth.priv.talos00 \
    auth.talos00 \
    bindery.talos00 \
    bookorbit.talos00 \
    booksonic.talos00 \
    catalyst.talos00 \
    chaptarr.talos00 \
    crowdsec.talos00 \
    dagster.talos00 \
    data.homepage.talos00 \
    dbgate.talos00 \
    dbgate.teak.talos00 \
    dungeon-library.talos00 \
    fchat.talos00 \
    guacamole.priv.talos00 \
    haven.talos00 \
    headlamp.priv.talos00 \
    home.homepage.talos00 \
    homepage.talos00 \
    hot-ones.priv.talos00 \
    hubble.talos00 \
    hyperdx.talos00 \
    immich.priv.talos00 \
    infra.homepage.talos00 \
    irc.talos00 \
    kavita.talos00 \
    komga.talos00 \
    kube-ops-view.talos00 \
    kubeview.talos00 \
    libation.talos00 \
    librarr.talos00 \
    livrarr.talos00 \
    llm.homepage.talos00 \
    lobechat.talos00 \
    logairr.talos00 \
    maintainerr.talos00 \
    manyfold.talos00 \
    media-explorer.talos00 \
    metube.talos00 \
    mylar3.talos00 \
    neo4j.talos00 \
    obs.homepage.talos00 \
    omnitools.talos00 \
    opengym.talos00 \
    plausible.talos00 \
    posterizarr.talos00 \
    posterr.talos00 \
    prowlarr.talos00 \
    pulsarr.talos00 \
    qbittorrent.talos00 \
    radarr.talos00 \
    registry.talos00 \
    sabnzbd.talos00 \
    scrypted.talos00 \
    searxng.talos00 \
    securexng.talos00 \
    seerr.talos00 \
    sonarr.talos00 \
    stackarr.talos00 \
    stash.priv.talos00 \
    storyteller.talos00 \
    tautulli.talos00 \
    tdarr.talos00 \
    theme.talos00 \
    traefik.talos00 \
    tubesync.talos00 \
    whisparr-eros.priv.talos00 \
    whisparr.priv.talos00 \
    whoami-auth.talos00 \
    whoami-tls.talos00 \
    whoami.priv.talos00 \
    windows-vnc.priv.talos00"
KD_HOSTS="amber.knowledgedump.space \
    analytics.knowledgedump.space \
    auth.knowledgedump.space \
    auth.priv.knowledgedump.space \
    bg.knowledgedump.space \
    boomtime.knowledgedump.space \
    dev.boomtime.knowledgedump.space \
    forge.knowledgedump.space \
    headscale.knowledgedump.space \
    immich.priv.knowledgedump.space \
    linkwarden.knowledgedump.space \
    registry.knowledgedump.space \
    scene-engine.priv.knowledgedump.space \
    stash-box.priv.knowledgedump.space \
    stash.priv.knowledgedump.space \
    trap.knowledgedump.space \
    whisparr-eros.priv.knowledgedump.space \
    whisparr.priv.knowledgedump.space \
    whoami.knowledgedump.space \
    whoami.priv.knowledgedump.space \
    zipline.knowledgedump.space"

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
  echo "--- weblan:8081 / websecurelan:8443 WAN-forwarded? (a8vo step 3 — settles the headline number) ---"
  echo "  :8081 weblan       root -> $(code -H 'Host: grafana.talos00' "http://${ORIGIN}:8081/")"
  echo "  :8443 websecurelan root -> $(code -H 'Host: grafana.talos00' "https://${ORIGIN}:8443/")"
  echo "--- 007 public route through Cloudflare (control) ---"
  echo "  zipline.amberdark.net -> $(code https://zipline.amberdark.net/)"

  # ─────────────────────────────────────────────────────────────────────────
  # BEEFED-UP BATTERY (2026-10-24) — the full sweep + dual-ingress semantics
  # ─────────────────────────────────────────────────────────────────────────
  echo "--- 006-FULL every *.talos00 host, host-spoofed at the origin :443 ---"
  echo "    EXPECT not-reachable: 403 (lan-only), 404 (route no-match), or 302->auth."
  echo "    A 200 or a 3xx to the SAME host = LAN service reachable off-net = FINDING."
  for h in $TALOS_HOSTS; do
    printf "  %-34s -> %s\n" "$h" "$(code -H "Host: ${h}" "https://${ORIGIN}/")"
  done
  echo "--- PUBLIC-SURFACE every *.knowledgedump.space host, direct via real DNS (MUST stay reachable) ---"
  echo "    EXPECT reachable/authed: 2xx / 3xx->auth / 401 / 403-authed. A 000 or 5xx = regression."
  for h in $KD_HOSTS; do
    printf "  %-40s -> %s\n" "$h" "$(code "https://${h}/")"
  done
  echo "--- APEX cross-contamination: can a public-looking Host reach a LAN service at the origin? ---"
  for hh in knowledgedump.space talos00 grafana.knowledgedump.space; do
    echo "  Host: ${hh} @ origin :443 -> $(code -H "Host: ${hh}" "https://${ORIGIN}/")"
  done
  echo "--- CERT identity at the origin apex (homelab-ca leak? expect a PUBLIC issuer, not homelab-ca) ---"
  for sni in grafana.talos00 forge.knowledgedump.space; do
    iss="$(echo | timeout 10 openssl s_client -connect "${ORIGIN}:443" -servername "$sni" 2> /dev/null | openssl x509 -noout -issuer 2> /dev/null)"
    echo "  SNI ${sni} -> ${iss:-<no cert / handshake failed>}"
  done
  echo "--- METHODS: TRACE / OPTIONS on the origin (TRACE 200 = XST risk) ---"
  for m in TRACE OPTIONS; do
    echo "  ${m} / (Host grafana.talos00) -> $(code -X "$m" -H 'Host: grafana.talos00' "https://${ORIGIN}/")"
  done

  echo "PROBE DONE — $(date -u +%FT%TZ)"
} 2>&1
