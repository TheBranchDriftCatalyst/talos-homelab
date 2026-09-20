#!/bin/sh
# Build the Catalyst nav manifest by DISCOVERY, never from a hardcoded list.
#
# Source of truth: the gethomepage.dev/* annotations already carried by every
# IngressRoute in this cluster (and auto-derived by the Kyverno
# `homepage-annotation-derivation` policy). Adding an app adds a nav entry;
# deleting one removes it. Nothing here knows any app's name.
#
# Whether an entry is "themed" is derived too: a route is themed iff it
# references a middleware named theme-*. Unthemed destinations are rendered
# dimmed so it is obvious you are leaving the styled set.
#
# Writes into the SAME emptyDir nginx serves from, so the file is published at
# /catalyst/resources/catalyst-nav.json with no extra nginx config and no pod
# restart when the cluster changes.
set -eu

OUT=/config/www/resources/catalyst-nav.json
INTERVAL="${NAV_REFRESH_SECONDS:-300}"

while :; do
  # Wait for the theme.park s6 init to have created the tree; on a cold start
  # this sidecar can win the race and would otherwise write into nothing.
  if [ -d /config/www/resources ]; then
    if kubectl get ingressroutes.traefik.io -A -o json 2> /dev/null > /tmp/ir.json; then
      if python3 /nav/build_nav.py < /tmp/ir.json > /tmp/nav.json 2> /tmp/nav.err; then
        # Atomic replace: nginx must never serve a half-written file.
        mv /tmp/nav.json "$OUT"
        echo "[nav] wrote $OUT ($(wc -c < "$OUT" | tr -d ' ') bytes, $(grep -o '"href"' "$OUT" | wc -l | tr -d ' ') entries)"
      else
        echo "[nav] build failed: $(cat /tmp/nav.err)" >&2
      fi
    else
      echo "[nav] kubectl list failed; keeping the previous manifest" >&2
    fi
  else
    echo "[nav] waiting for /config/www/resources"
  fi
  sleep "$INTERVAL"
done
