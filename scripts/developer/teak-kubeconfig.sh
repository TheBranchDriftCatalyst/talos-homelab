#!/usr/bin/env bash
# ╔══════════════════════════════════════════════════════════════════════════════╗
# ║  teak-talos-dev — mint a namespace-scoped kubeconfig for the work laptop     ║
# ╚══════════════════════════════════════════════════════════════════════════════╝
#
# Emits a standalone kubeconfig authenticating as the `teak-operator` ServiceAccount.
# That identity holds a namespaced Role in teak-talos-dev, plus a read-only ClusterRole over
# `namespaces` and `nodes` (cluster/env pickers need to list both, and a Role cannot express a
# collection read over a cluster-scoped resource). It cannot read or modify any OBJECT outside
# teak-talos-dev.
#
# The credential comes from the TokenRequest API (`kubectl create token`), NOT a legacy
# service-account-token Secret: auto-population of those is deprecated and this cluster has
# none. This apiserver grants the full 365 days requested.
#
# Usage:
#   ./scripts/developer/teak-kubeconfig.sh            # mint a 365-day kubeconfig
#   ./scripts/developer/teak-kubeconfig.sh --rotate   # REVOKE all existing tokens, then mint
#
# Then on the work laptop — see infrastructure/base/teak-talos-dev/ONBOARDING.md
set -euo pipefail

NS="teak-talos-dev"
SA="teak-operator"
CONTEXT_NAME="teak-talos-dev"
OUT="${OUT:-.output/teak-talos-dev.kubeconfig}"
DURATION="${TEAK_TOKEN_DURATION:-8760h}" # 365d; this apiserver grants it in full
# LAN address of the control plane. Change here if the endpoint ever moves.
SERVER="${TEAK_SERVER:-https://192.168.1.54:6443}"
RBAC_FILE="infrastructure/base/teak-talos-dev/rbac.yaml"

die() {
  echo "ERROR: $*" >&2
  exit 1
}

# ── Fail fast and explain, rather than hanging on a namespace that doesn't exist ──────────
if ! kubectl get namespace "$NS" > /dev/null 2>&1; then
  cat >&2 << MSG
ERROR: namespace '${NS}' does not exist — the tenant has not been deployed yet.

  This namespace is Flux-managed. Deploying it means committing and pushing:

      git add infrastructure/base/teak-talos-dev clusters/catalyst-cluster/teak-talos-dev*.yaml
      git commit -m "feat(teak-talos-dev): isolated work tenant"
      git push
      task infra:flux-reconcile     # or wait for the interval

  Then re-run this script.
MSG
  exit 1
fi

kubectl -n "$NS" get serviceaccount "$SA" > /dev/null 2>&1 ||
  die "ServiceAccount ${NS}/${SA} not found. Has the '${NS}' Flux Kustomization reconciled? (flux get kustomization ${NS})"

# ── Rotation: recreating the SA invalidates every previously issued token (they are bound to
#    the SA's UID). A plain re-mint does NOT revoke anything — TokenRequest tokens cannot be
#    individually revoked. ──────────────────────────────────────────────────────────────────
if [[ "${1:-}" == "--rotate" ]]; then
  echo "==> revoking: deleting ServiceAccount ${NS}/${SA} (invalidates ALL issued tokens)"
  kubectl -n "$NS" delete serviceaccount "$SA"
  echo "==> recreating it"
  [[ -f "$RBAC_FILE" ]] || die "cannot find ${RBAC_FILE} — run this from the repo root"
  kubectl apply -f "$RBAC_FILE" > /dev/null
  kubectl -n "$NS" get serviceaccount "$SA" > /dev/null
fi

echo "==> minting a ${DURATION} token for ${NS}/${SA}"
TOKEN="$(kubectl -n "$NS" create token "$SA" --duration="$DURATION")"
[[ -n "$TOKEN" ]] || die "TokenRequest returned an empty token"

# Cluster CA: every namespace carries it in the kube-root-ca.crt ConfigMap. Fall back to the
# CA embedded in the current kubeconfig if that ConfigMap is ever absent.
CA_PEM="$(kubectl -n "$NS" get configmap kube-root-ca.crt -o jsonpath='{.data.ca\.crt}' 2> /dev/null || true)"
if [[ -n "$CA_PEM" ]]; then
  CA_B64="$(printf '%s' "$CA_PEM" | base64 | tr -d '\n')"
else
  CA_B64="$(kubectl config view --raw --minify -o jsonpath='{.clusters[0].cluster.certificate-authority-data}')"
fi
[[ -n "$CA_B64" ]] || die "could not resolve the cluster CA"

mkdir -p "$(dirname "$OUT")"
cat > "$OUT" << KUBECONFIG
apiVersion: v1
kind: Config
clusters:
  - name: ${CONTEXT_NAME}
    cluster:
      server: ${SERVER}
      certificate-authority-data: ${CA_B64}
users:
  - name: ${SA}
    user:
      token: ${TOKEN}
contexts:
  - name: ${CONTEXT_NAME}
    context:
      cluster: ${CONTEXT_NAME}
      user: ${SA}
      namespace: ${NS}
current-context: ${CONTEXT_NAME}
KUBECONFIG
chmod 600 "$OUT"

# Report the real expiry decoded from the token, not the duration we asked for.
PAYLOAD="$(printf '%s' "$TOKEN" | cut -d. -f2)"
EXPIRY="$(python3 -c "
import base64, json, sys, datetime
p = sys.argv[1]; p += '=' * (-len(p) % 4)
c = json.loads(base64.urlsafe_b64decode(p))
print(datetime.datetime.fromtimestamp(c['exp'], datetime.timezone.utc).strftime('%Y-%m-%d'))
" "$PAYLOAD" 2> /dev/null || echo unknown)"

echo "✅ wrote ${OUT}  (expires ${EXPIRY})"
echo
echo "   Verify (expect: yes, then no):"
echo "     KUBECONFIG=${OUT} kubectl auth can-i create clusters.postgresql.cnpg.io"
echo "     KUBECONFIG=${OUT} kubectl auth can-i list pods -n kube-system"
echo
echo "   Copy to the work laptop (see infrastructure/base/teak-talos-dev/ONBOARDING.md):"
echo "     scp ${OUT} <laptop>:~/.kube/teak-talos-dev"
echo "     export KUBECONFIG=~/.kube/teak-talos-dev"
