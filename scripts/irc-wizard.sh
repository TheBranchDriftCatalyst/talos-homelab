#!/usr/bin/env bash
# ╔══════════════════════════════════════════════════════════════════════════════╗
# ║  IRC wizard — manage The Lounge users and themes                             ║
# ╚══════════════════════════════════════════════════════════════════════════════╝
#
# WHY THIS IS SHORT
#
# It replaced a much longer soju wizard. Under soju, everything — accounts,
# upstream networks, per-network nicks, SASL, channel joins — had to be driven
# through an admin unix socket inside a distroless pod, because neither the
# bouncer nor its minimal web client could do any of it.
#
# The Lounge only needs this for USER accounts. Networks, channels, the channel
# list, SASL and nick settings are all done in the web UI by the user
# themselves, which is precisely why we moved.
#
# Accounts live on the PVC at /var/opt/thelounge/users/<name>.json, NOT in git.
# They survive restarts and redeploys; they do not survive losing the volume.

set -euo pipefail

NS="${IRC_NAMESPACE:-irc}"
DEPLOY="${IRC_DEPLOYMENT:-deploy/thelounge}"
URL="${IRC_URL:-https://irc.talos00}"

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

# The Lounge prints a startup banner and a config-owner warning on every CLI
# invocation (the config is a read-only ConfigMap mount owned by root while the
# process runs as uid 1000). Both are noise here, not problems.
tl() {
  kubectl -n "$NS" exec "$DEPLOY" -- thelounge "$@" 2>&1 |
    grep -viE "WARN|correct system user|thelounge\.chat/docs|ExperimentalWarning|trace-warnings" || true
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
    die "cannot reach $DEPLOY in namespace $NS (cluster up? kubeconfig merged?)"
}

list_users() {
  info "users"
  tl list | sed 's/^/  /'
}

add_user() {
  info "add a user"
  local username password gen logs
  prompt username "username"
  if [ -z "$username" ]; then
    warn "no username given"
    return 0
  fi

  prompt gen "generate a random password? [Y/n]" "Y"
  case "$gen" in
    [nN]*)
      read -r -s -p "  password: " password
      say ""
      ;;
    *) password="$(openssl rand -base64 18 | tr -d '/+=' | cut -c1-20)" ;;
  esac
  if [ -z "$password" ]; then
    warn "empty password, aborting"
    return 0
  fi

  # --save-logs is only honoured when --password is given non-interactively,
  # and without it this user's scrollback is memory-only and dies with the pod.
  prompt logs "persist scrollback to disk for this user? [Y/n]" "Y"

  local args=(add --password "$password")
  case "$logs" in [nN]*) ;; *) args+=(--save-logs) ;; esac
  args+=("$username")

  say ""
  say "  ${c_dim}thelounge add --password <hidden> ${logs:+--save-logs }${username}${c_reset}"
  local reply
  read -r -p "  create this user? [y/N] " reply
  case "$reply" in [yY]*) ;; *)
    warn "skipped"
    return 0
    ;;
  esac

  tl "${args[@]}" | sed 's/^/  /'
  ok "created"
  say ""
  say "  ${c_bold}save these — log in at ${URL}${c_reset}"
  say "    username: ${username}"
  say "    password: ${password}"
  say ""
  say "  ${c_dim}Networks and channels are added in the web UI after logging in.${c_reset}"
  warn "this account lives on the PVC, not in git — losing the volume loses it."
}

remove_user() {
  info "remove a user"
  tl list | sed 's/^/  /'
  local username reply
  prompt username "username to REMOVE"
  if [ -z "$username" ]; then
    warn "no username given"
    return 0
  fi
  say ""
  warn "this deletes ${username}'s account, saved networks and scrollback."
  read -r -p "  type the username again to confirm: " reply
  if [ "$reply" != "$username" ]; then
    warn "mismatch, aborting"
    return 0
  fi
  tl remove "$username" | sed 's/^/  /'
  ok "removed"
}

install_theme() {
  info "install a theme or package"
  say "  ${c_dim}browse: https://thelounge.chat/docs/guides/themes ${c_reset}"
  say "  ${c_dim}e.g. thelounge-theme-morning, thelounge-theme-zenburn${c_reset}"
  local pkg
  prompt pkg "package name"
  if [ -z "$pkg" ]; then
    warn "no package given"
    return 0
  fi
  tl install "$pkg" | sed 's/^/  /'
  ok "installed — select it in the UI under Settings, or set 'theme' in config.js"
  warn "installed packages live on the PVC. To make it survive a volume rebuild,"
  warn "add it to the manifest instead of relying on this."
}

status() {
  info "status"
  say "  ${c_bold}pods${c_reset}"
  kubectl -n "$NS" get pods --no-headers | sed 's/^/    /'
  say ""
  say "  ${c_bold}users${c_reset}"
  tl list | sed 's/^/    /'
  say ""
  say "  ${c_bold}endpoint${c_reset}"
  printf '    %s -> ' "$URL"
  curl -sk -o /dev/null -w '%{http_code}\n' --max-time 10 "$URL/" || say "unreachable"
  say "    ${c_dim}302 is correct: Authentik gates the page before The Lounge sees it.${c_reset}"
}

menu() {
  while true; do
    say ""
    say "${c_bold}IRC wizard${c_reset} ${c_dim}(The Lounge, namespace: ${NS})${c_reset}"
    say "  1) list users"
    say "  2) add a user"
    say "  3) remove a user"
    say "  4) install a theme/package"
    say "  5) status"
    say "  q) quit"
    local choice
    read -r -p "  choose: " choice
    case "$choice" in
      1) list_users ;;
      2) add_user ;;
      3) remove_user ;;
      4) install_theme ;;
      5) status ;;
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
