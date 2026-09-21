#!/usr/bin/env bash
# ╔══════════════════════════════════════════════════════════════════════════════╗
# ║  soju wizard — provision IRC bouncer accounts, networks and channels         ║
# ╚══════════════════════════════════════════════════════════════════════════════╝
#
# WHY THIS EXISTS
#
# soju has no self-registration and no web admin: accounts are created only
# through an admin unix socket inside the pod, and the image is distroless, so
# there is not even a shell in there to work from. Everything therefore goes
# through `kubectl exec ... sojuctl`, which is fine once but miserable to
# remember, and the flag surface is not guessable (`user list` does not exist;
# `channel create` needs a #chan/network address, not a bare name).
#
# THE MODEL, which the prompts below follow:
#
#   soju account            one bouncer login (what you type into gamja)
#    └── network            one upstream server, with ITS OWN nick + SASL creds
#         └── channel       joined persistently; survives you closing the tab
#
# So one account fronts many networks, and your nick can differ per network.
#
# Read-only by default: every action that changes something prints the exact
# sojuctl command and asks before running it.

set -euo pipefail

NS="${SOJU_NAMESPACE:-irc}"
DEPLOY="${SOJU_DEPLOYMENT:-deploy/soju}"

c_reset=$'\033[0m'
c_dim=$'\033[2m'
c_bold=$'\033[1m'
c_cyan=$'\033[36m'
c_green=$'\033[32m'
c_yellow=$'\033[33m'
c_red=$'\033[31m'

say() { printf '%s\n' "$*"; }
info() { printf '%s==>%s %s\n' "$c_cyan" "$c_reset" "$*"; }
ok() { printf '%s ok %s %s\n' "$c_green" "$c_reset" "$*"; }
warn() { printf '%s  ! %s %s\n' "$c_yellow" "$c_reset" "$*"; }
die() {
  printf '%s fail%s %s\n' "$c_red" "$c_reset" "$*" >&2
  exit 1
}

# Run a sojuctl command in the soju pod. All output is returned to the caller.
sojuctl() { kubectl -n "$NS" exec "$DEPLOY" -- sojuctl "$@" 2>&1; }

# Show a command, ask, then run it. Returns the command's own exit status.
confirm_run() {
  local desc="$1"
  shift
  say ""
  say "  ${c_bold}${desc}${c_reset}"
  say "  ${c_dim}sojuctl $*${c_reset}"
  local reply
  read -r -p "  run this? [y/N] " reply
  case "$reply" in
    [yY]*) ;;
    *)
      warn "skipped"
      return 130
      ;;
  esac
  local out status
  out="$(sojuctl "$@")" && status=0 || status=$?
  [ -n "$out" ] && say "  ${c_dim}${out}${c_reset}"
  if [ "$status" -eq 0 ]; then
    ok "done"
  elif printf '%s' "$out" | grep -qiE "already exists|already in use"; then
    # Idempotence: re-running the wizard must not look like a failure.
    ok "already present — nothing to do"
    status=0
  else
    warn "command failed (exit $status)"
  fi
  return "$status"
}

prompt() { # prompt <varname> <question> [default]
  local __var="$1" __q="$2" __def="${3:-}" __ans
  if [ -n "$__def" ]; then
    read -r -p "  ${__q} [${__def}]: " __ans
    __ans="${__ans:-$__def}"
  else
    read -r -p "  ${__q}: " __ans
  fi
  printf -v "$__var" '%s' "$__ans"
}

preflight() {
  command -v kubectl > /dev/null 2>&1 || die "kubectl not found in PATH"
  kubectl -n "$NS" get "$DEPLOY" > /dev/null 2>&1 ||
    die "cannot reach $DEPLOY in namespace $NS (is the cluster up, kubeconfig merged?)"
  # Proves the admin socket is actually listening — without it every command
  # fails with "no listen unix+admin directive found in config".
  if ! sojuctl help > /dev/null 2>&1; then
    die "sojuctl is not usable. Check that soju's config has: listen unix+admin:///run/soju/admin"
  fi
}

show_status() {
  info "soju status"
  local u
  prompt u "username to inspect (blank = skip)" ""
  [ -z "$u" ] && return 0
  say ""
  say "  ${c_bold}user${c_reset}"
  sojuctl user status "$u" | sed 's/^/    /'
  say ""
  say "  ${c_bold}networks${c_reset}"
  sojuctl user run "$u" network status | sed 's/^/    /'
  say ""
  say "  ${c_bold}channels${c_reset}"
  sojuctl user run "$u" channel status | sed 's/^/    /'
}

add_user() {
  info "add a soju account (this is the login you type into gamja)"
  local username password admin gen
  prompt username "username"
  [ -z "$username" ] && {
    warn "no username given"
    return 0
  }

  prompt gen "generate a random password? [Y/n]" "Y"
  case "$gen" in
    [nN]*)
      read -r -s -p "  password: " password
      say ""
      ;;
    *) password="$(openssl rand -base64 18 | tr -d '/+=' | cut -c1-20)" ;;
  esac
  [ -z "$password" ] && {
    warn "empty password, aborting"
    return 0
  }

  prompt admin "make this user a soju admin? [y/N]" "N"

  local args=(user create -username "$username" -password "$password")
  case "$admin" in [yY]*) args+=(-admin) ;; esac

  if confirm_run "create account '${username}'" "${args[@]}"; then
    say ""
    say "  ${c_bold}save these — the password is not recoverable later${c_reset}"
    say "    username: ${username}"
    say "    password: ${password}"
    say ""
    warn "this account exists only in soju's Postgres, not in git."
    warn "a fresh database means recreating it."
  fi
}

add_network() {
  info "add an upstream network to an account"
  say "  ${c_dim}each network keeps its OWN nick and SASL credentials${c_reset}"
  local username netname addr nick
  prompt username "which soju account"
  [ -z "$username" ] && {
    warn "no account given"
    return 0
  }

  say ""
  say "  common networks:"
  say "    1) Libera.Chat  irc.libera.chat  ${c_dim}(FOSS projects: #python, #kubernetes, #soju)${c_reset}"
  say "    2) OFTC         irc.oftc.net     ${c_dim}(Debian, Tor)${c_reset}"
  say "    3) something else"
  local choice
  prompt choice "choose" "1"
  case "$choice" in
    1)
      addr="irc.libera.chat"
      netname="libera"
      ;;
    2)
      addr="irc.oftc.net"
      netname="oftc"
      ;;
    *)
      prompt addr "server address (host or ircs://host:port)"
      prompt netname "short name for it"
      ;;
  esac
  [ -z "$addr" ] && {
    warn "no address"
    return 0
  }

  prompt nick "nick to use on ${netname}" "$username"

  confirm_run "connect '${username}' to ${netname} (${addr}) as ${nick}" \
    user run "$username" network create -addr "$addr" -name "$netname" -nick "$nick" || true

  say ""
  say "  ${c_dim}Next: register the nick with NickServ, then add SASL here so soju${c_reset}"
  say "  ${c_dim}authenticates automatically on every reconnect (menu option 4).${c_reset}"
}

add_channels() {
  info "join channels on a network (persistently — they stay joined)"
  local username netname chans
  prompt username "which soju account"
  prompt netname "which network" "libera"
  # A plain `[ -z a ] || [ -z b ] && { ...; }` reads as (A||B)&&C and leaves the
  # line non-zero when both are set, which under `set -e` can abort the wizard.
  if [ -z "$username" ] || [ -z "$netname" ]; then
    warn "need account and network"
    return 0
  fi

  say "  ${c_dim}space-separated, e.g: #soju #kubernetes #python${c_reset}"
  prompt chans "channels"
  [ -z "$chans" ] && {
    warn "no channels given"
    return 0
  }

  local ch detach
  prompt detach "join detached? (buffered but not shown until activity) [y/N]" "N"

  for ch in $chans; do
    case "$ch" in \#*) ;; *) ch="#${ch}" ;; esac
    # soju addresses channels as #chan/network when not in a network context.
    local target="${ch}/${netname}"
    case "$detach" in
      [yY]*) confirm_run "join ${ch} on ${netname} (detached)" \
        user run "$username" channel create "$target" -detached true || true ;;
      *) confirm_run "join ${ch} on ${netname}" \
        user run "$username" channel create "$target" || true ;;
    esac
  done
}

set_sasl() {
  info "set SASL so soju identifies to the network automatically"
  say "  ${c_dim}Register the nick first: /msg NickServ REGISTER <password> <email>${c_reset}"
  local username netname sasluser saslpass
  prompt username "which soju account"
  prompt netname "which network" "libera"
  prompt sasluser "NickServ account name" "$username"
  read -r -s -p "  NickServ password: " saslpass
  say ""
  [ -z "$saslpass" ] && {
    warn "empty password, aborting"
    return 0
  }

  confirm_run "set SASL for ${username} on ${netname}" \
    user run "$username" sasl set-plain "$sasluser" "$saslpass" || true
  warn "if this fails, the network may need selecting first — check: sojuctl user run $username sasl status"
}

menu() {
  while true; do
    say ""
    say "${c_bold}soju wizard${c_reset} ${c_dim}(namespace: ${NS})${c_reset}"
    say "  1) add an account"
    say "  2) add a network to an account"
    say "  3) join channels on a network"
    say "  4) set SASL for a network"
    say "  5) show status"
    say "  q) quit"
    local choice
    read -r -p "  choose: " choice
    case "$choice" in
      1) add_user ;;
      2) add_network ;;
      3) add_channels ;;
      4) set_sasl ;;
      5) show_status ;;
      q | Q)
        say "bye"
        return 0
        ;;
      *) warn "unknown choice" ;;
    esac
  done
}

preflight
menu
