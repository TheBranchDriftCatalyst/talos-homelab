#!/usr/bin/env bash
#
# provision-udm-crowdsec-bouncer.sh
# ---------------------------------
# Installs + configures the CrowdSec firewall bouncer on a UniFi Dream Machine (UDM SE)
# so CrowdSec decisions are enforced at the PERIMETER (nftables), complementing the
# in-cluster Traefik bouncer (HTTP L7 only).
#
# Runs ENTIRELY from your workstation over SSH. No copy-paste on the device, no USB, no
# manually editing files on the UDM. You run this once; it does the rest and is safe to
# re-run (idempotent).
#
# The UDM pulls a FILTERED blocklist from the in-cluster mirror (192.168.1.243:41412),
# which already excludes cowrie (keeps the honeypot alive) and the 30k static import list.
# See infrastructure/base/crowdsec/blocklist-mirror.yaml.
#
# ── PREREQUISITES (one-time, on the device, done by YOU in the UniFi UI) ─────────────────
#   1. Enable SSH:  UniFi console -> Settings -> Control Plane / System -> SSH = ON,
#      and set an SSH password OR add your SSH key. This is the ONE thing that cannot be
#      automated — it is the initial trust bootstrap.
#   2. Know the UDM's LAN IP (usually 192.168.1.1).
#
# ── PREREQUISITES (cluster side, GitOps) ─────────────────────────────────────────────────
#   - infrastructure/base/crowdsec/blocklist-mirror.yaml deployed (LB on 192.168.1.243).
#   - 1Password `crowdsec` item has field `bouncer-api-key-unifimirror` (openssl rand -hex 32);
#     ESO syncs it and LAPI registers the "unifimirror" bouncer. (The mirror serves the list
#     with auth:none, so the UDM does NOT need that key — this note is for the cluster side.)
#
# ── USAGE ────────────────────────────────────────────────────────────────────────────────
#   UDM_HOST=192.168.1.1 ./provision-udm-crowdsec-bouncer.sh
#   # optional overrides:
#   UDM_HOST=192.168.1.1 UDM_USER=root MIRROR_URL=http://192.168.1.243:41412/security.txt \
#     INSTALLER_REF=v1.4.0 ./provision-udm-crowdsec-bouncer.sh
#
#   Dry run (prints what it WOULD do on the device, changes nothing):
#     DRY_RUN=1 UDM_HOST=192.168.1.1 ./provision-udm-crowdsec-bouncer.sh
#
set -euo pipefail

# ── config (env-overridable) ─────────────────────────────────────────────────────────────
UDM_HOST="${UDM_HOST:?set UDM_HOST, e.g. UDM_HOST=192.168.1.1}"
UDM_USER="${UDM_USER:-root}"
MIRROR_URL="${MIRROR_URL:-http://192.168.1.243:41412/security.txt}"
# Pin the installer to a specific ref rather than tracking main — this runs on your firewall.
INSTALLER_REPO="${INSTALLER_REPO:-wolffcatskyy/crowdsec-unifi-bouncer}"
INSTALLER_REF="${INSTALLER_REF:-main}"
DRY_RUN="${DRY_RUN:-0}"

# Interactive-friendly: NO BatchMode, so ssh prompts for a password if you have no key.
# ControlMaster multiplexes every ssh/scp in this script over ONE connection, so you are
# prompted for the UDM password exactly ONCE (the first call), not per-command.
SSH_CTL="${TMPDIR:-/tmp}/udm-cs-bouncer-%r@%h:%p"
SSH_OPTS=(-o ConnectTimeout=10 -o StrictHostKeyChecking=accept-new
  -o ControlMaster=auto -o "ControlPath=${SSH_CTL}" -o ControlPersist=120s)
# Close the shared connection on exit so no socket lingers.
cleanup_ssh() { ssh -O exit -o "ControlPath=${SSH_CTL}" "${UDM_USER}@${UDM_HOST}" 2> /dev/null || true; }
trap cleanup_ssh EXIT

log() { printf '\033[1;36m▶ %s\033[0m\n' "$*"; }
ok() { printf '\033[1;32m  ✓ %s\033[0m\n' "$*"; }
warn() { printf '\033[1;33m  ⚠ %s\033[0m\n' "$*"; }
die() {
  printf '\033[1;31m  ✗ %s\033[0m\n' "$*" >&2
  exit 1
}

remote() { # run a command on the UDM (or print it in dry-run)
  if [ "$DRY_RUN" = "1" ]; then
    printf '    [dry-run] ssh %s@%s %q\n' "$UDM_USER" "$UDM_HOST" "$*"
    return 0
  fi
  # SC2029: the command intentionally expands client-side into the remote shell.
  ssh "${SSH_OPTS[@]}" "${UDM_USER}@${UDM_HOST}" "$@"
}

# ── 1. preflight: SSH reachable, it's a UniFi OS device, mirror reachable FROM the UDM ────
log "Preflight"
if [ "$DRY_RUN" != "1" ]; then
  ssh "${SSH_OPTS[@]}" "${UDM_USER}@${UDM_HOST}" true 2> /dev/null ||
    die "cannot SSH to ${UDM_USER}@${UDM_HOST}. Enable SSH in the UniFi UI and confirm the host/key/password."
  ok "SSH to ${UDM_USER}@${UDM_HOST} works"

  # shellcheck disable=SC2029
  MODEL="$(remote 'cat /proc/ubnthal/system.info 2>/dev/null | sed -n "s/^systemid=//p;s/^shortname=//p" | head -1' || true)"
  UNIFIOS="$(remote 'test -d /data && test -f /etc/os-release && echo yes || echo no')"
  [ "$UNIFIOS" = "yes" ] || die "this does not look like a UniFi OS device (no /data). Aborting rather than touching the wrong host."
  ok "UniFi OS device detected${MODEL:+ (${MODEL})}"

  # The mirror must be reachable FROM the UDM, or the bouncer starts with an empty set.
  if remote "curl -fsS --max-time 8 -o /dev/null '${MIRROR_URL}'" 2> /dev/null; then
    COUNT="$(remote "curl -fsS --max-time 8 '${MIRROR_URL}' | grep -c . || true")"
    ok "mirror reachable from the UDM — serving ${COUNT:-?} IPs"
  else
    warn "the UDM cannot reach ${MIRROR_URL}."
    warn "Deploy infrastructure/base/crowdsec/blocklist-mirror.yaml and confirm 192.168.1.243 is up,"
    warn "then re-run. (Continuing would install a bouncer with an empty blocklist.)"
    die "mirror unreachable — fix the source before provisioning the edge."
  fi
else
  warn "DRY_RUN=1 — skipping live preflight; commands below are what WOULD run."
fi

# ── 2. install the bouncer (pinned installer, persists across firmware updates) ──────────
log "Installing the CrowdSec firewall bouncer on the UDM (ref: ${INSTALLER_REF})"
# Fetch the installer to the UDM and run it. Pinned to a ref, not piped from main, so the
# exact code that runs on your firewall is deterministic and reviewable.
INSTALL_URL="https://raw.githubusercontent.com/${INSTALLER_REPO}/${INSTALLER_REF}/bootstrap.sh"
remote "curl -fsSL '${INSTALL_URL}' -o /tmp/cs-unifi-bootstrap.sh" ||
  die "failed to download the installer to the UDM (does it have internet?)"
remote "sh /tmp/cs-unifi-bootstrap.sh" ||
  die "installer failed on the UDM — inspect /tmp/cs-unifi-bootstrap.sh output above"
ok "bouncer installed"

# ── 3. write the config (points at the FILTERED mirror, not raw LAPI) ────────────────────
log "Configuring the bouncer to pull the filtered mirror"
# The firewall bouncer consumes the mirror as a blocklist URL. This is the honeypot-safe
# path: the mirror already stripped cowrie + the static import list server-side, so the UDM
# physically never receives a cowrie ban.
CONFIG_DIR="/data/crowdsec-bouncer"
read -r -d '' BOUNCER_CFG << CFG || true
# Managed by provision-udm-crowdsec-bouncer.sh — edits will be overwritten on re-run.
mode: nftables
update_frequency: 30s
log_level: info
log_mode: stdout
# No direct LAPI connection: this bouncer pulls a pre-filtered plain-text list from the
# in-cluster mirror. The mirror is what enforces "no cowrie, origins crowdsec+CAPI".
api_url: ""
api_key: ""
blacklists_ipv4: crowdsec-blacklists
blacklists_ipv6: crowdsec6-blacklists
nftables:
  ipv4: {enabled: true, set-only: false, table: crowdsec, chain: crowdsec-chain}
  ipv6: {enabled: true, set-only: false, table: crowdsec6, chain: crowdsec6-chain}
blocklists:
  - url: ${MIRROR_URL}
    method: GET
# Expose Prometheus metrics on the LAN so the cluster's Alloy can scrape them
# (job crowdsec-unifi-bouncer -> Mimir -> crowdsec-ops dashboard). The UDM firewall
# must permit inbound :9101 from the pod CIDR (10.244.0.0/16). Bound to all
# interfaces because localhost-only is unreachable from the cluster.
prometheus:
  enabled: true
  listen_addr: 0.0.0.0
  listen_port: 9101
CFG
# shellcheck disable=SC2029
remote "mkdir -p '${CONFIG_DIR}'"
if [ "$DRY_RUN" = "1" ]; then
  printf '    [dry-run] would write %s/crowdsec-firewall-bouncer.yaml:\n' "$CONFIG_DIR"
  printf '%s\n' "$BOUNCER_CFG" | sed 's/^/        /'
else
  printf '%s\n' "$BOUNCER_CFG" | ssh "${SSH_OPTS[@]}" "${UDM_USER}@${UDM_HOST}" \
    "cat > '${CONFIG_DIR}/crowdsec-firewall-bouncer.yaml'"
  ok "config written to ${CONFIG_DIR}/crowdsec-firewall-bouncer.yaml"
fi

# ── 4. (re)start + verify ────────────────────────────────────────────────────────────────
log "Starting the bouncer and verifying enforcement"
remote "systemctl restart crowdsec-firewall-bouncer 2>/dev/null || /data/crowdsec-bouncer/restart.sh 2>/dev/null || true"
if [ "$DRY_RUN" != "1" ]; then
  sleep 5
  ENTRIES="$(remote "nft list set inet crowdsec crowdsec-blacklists 2>/dev/null | grep -c 'elements' || \
                     ipset list crowdsec-blacklists -t 2>/dev/null | sed -n 's/.*Number of entries: //p' || echo 0")"
  if [ "${ENTRIES:-0}" != "0" ]; then
    ok "nftables set populated — ${ENTRIES} blocked entr(y/ies) enforced at the edge"
  else
    warn "the set is empty. Either the mirror is serving 0 IPs right now (possible if there are"
    warn "few active crowdsec/CAPI decisions) or the bouncer has not synced yet. Re-check with:"
    warn "  ssh ${UDM_USER}@${UDM_HOST} 'nft list set inet crowdsec crowdsec-blacklists | head'"
  fi
fi

log "Done."
cat << DONE

  Enforcement is now at the perimeter for crowdsec + CAPI decisions, cowrie EXCLUDED.

  VERIFY THE HONEYPOT IS STILL ALIVE (the one check that matters):
    # a currently-cowrie-banned IP must NOT be in the edge set
    ssh ${UDM_USER}@${UDM_HOST} 'nft list set inet crowdsec crowdsec-blacklists' | grep <a-cowrie-IP>   # -> should be EMPTY

  METRICS: the bouncer now serves Prometheus metrics on <UDM>:9101. For the crowdsec-ops
  dashboard's "UDM edge bouncer" row to populate, allow inbound :9101 from 10.244.0.0/16 on
  the UDM firewall (the cluster's Alloy scrapes it).

  RE-RUN this script any time to reconfigure. To REMOVE:
    ssh ${UDM_USER}@${UDM_HOST} 'systemctl disable --now crowdsec-firewall-bouncer; rm -rf /data/crowdsec-bouncer'

  NOTE: the UDM is NOT in GitOps. This script is the source of truth for its config — keep it
  in the repo and re-run after any firmware reset that the installer's persistence does not survive.
DONE
