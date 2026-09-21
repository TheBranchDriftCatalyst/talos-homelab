#!/bin/sh
# Refresh the ConfigMap that supplies the talos00 certificate's SAN list.
#
# Writes ONLY a ConfigMap — never the Certificate. Flux substitutes the value
# into Certificate.spec.dnsNames at reconcile time, so Flux stays the sole
# writer of that resource and there is nothing for the two to fight over.
#
# NOT `set -e` on the whole script: a failed kubectl during an API blip must
# leave the previous SAN list in place, not tear it down.
set -u

NS=flux-system
CM=talos00-cert-sans
KEY=TALOS00_DNSNAMES

if ! kubectl get ingressroutes.traefik.io -A -o json > /tmp/ir.json 2> /tmp/err; then
  echo "[sans] kubectl list failed, keeping the existing list: $(cat /tmp/err)" >&2
  exit 0
fi

if ! NEW=$(python3 /sans/derive_sans.py < /tmp/ir.json 2> /tmp/err); then
  echo "[sans] derivation failed, keeping the existing list: $(cat /tmp/err)" >&2
  exit 0
fi

# A derivation that produced nothing but the constants means discovery found no
# routes at all — almost certainly a transient API problem rather than a cluster
# with no ingress. Refuse to shrink the certificate on that basis.
COUNT=$(echo "$NEW" | tr ',' '\n' | wc -l | tr -d ' ')
if [ "$COUNT" -lt 5 ]; then
  echo "[sans] only $COUNT names derived; refusing to shrink the cert" >&2
  exit 0
fi

OLD=$(kubectl -n "$NS" get configmap "$CM" -o "jsonpath={.data.$KEY}" 2> /dev/null || echo "")

if [ "$NEW" = "$OLD" ]; then
  echo "[sans] unchanged ($COUNT names)"
  exit 0
fi

# Idempotent create-or-update. Only ever runs when the list actually changed —
# every write here eventually reissues the certificate, so needless churn is
# the thing to avoid.
kubectl -n "$NS" create configmap "$CM" \
  --from-literal="$KEY=$NEW" \
  --dry-run=client -o yaml | kubectl apply -f - > /dev/null &&
  echo "[sans] updated: $COUNT names" ||
  echo "[sans] apply failed" >&2
