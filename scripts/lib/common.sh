#!/usr/bin/env bash
# ╔══════════════════════════════════════════════════════════════════════════════╗
# ║                                                                              ║
# ║   ████████╗ █████╗ ██╗      ██████╗ ███████╗     ██████╗ ██████╗ ███████╗   ║
# ║   ╚══██╔══╝██╔══██╗██║     ██╔═══██╗██╔════╝    ██╔═══██╗██╔══██╗██╔════╝   ║
# ║      ██║   ███████║██║     ██║   ██║███████╗    ██║   ██║██████╔╝███████╗   ║
# ║      ██║   ██╔══██║██║     ██║   ██║╚════██║    ██║   ██║██╔═══╝ ╚════██║   ║
# ║      ██║   ██║  ██║███████╗╚██████╔╝███████║    ╚██████╔╝██║     ███████║   ║
# ║      ╚═╝   ╚═╝  ╚═╝╚══════╝ ╚═════╝ ╚══════╝     ╚═════╝ ╚═╝     ╚══════╝   ║
# ║                                                                              ║
# ║                    Shared Shell Library for Talos Homelab                    ║
# ║                     Synthpunk Cyberwave Corporate Edition                    ║
# ║                                                                              ║
# ╚══════════════════════════════════════════════════════════════════════════════╝
#
# Source this file in your scripts:
#   source "$(dirname "${BASH_SOURCE[0]}")/../lib/common.sh"
#
# shellcheck disable=SC2034,SC2155

# ══════════════════════════════════════════════════════════════════════════════
# STRICT MODE
# ══════════════════════════════════════════════════════════════════════════════
set -euo pipefail

# ══════════════════════════════════════════════════════════════════════════════
# COLOR PALETTE - Synthpunk Cyberwave Theme
# ══════════════════════════════════════════════════════════════════════════════
# Core Colors
export RESET='\033[0m'
export BOLD='\033[1m'
export DIM='\033[2m'
export ITALIC='\033[3m'
export UNDERLINE='\033[4m'
export BLINK='\033[5m'
export REVERSE='\033[7m'

# Standard Colors
export BLACK='\033[30m'
export RED='\033[91m'
export GREEN='\033[92m'
export YELLOW='\033[93m'
export BLUE='\033[94m'
export MAGENTA='\033[95m'
export CYAN='\033[96m'
export WHITE='\033[97m'

# Darker Variants
export DARK_RED='\033[31m'
export DARK_GREEN='\033[32m'
export DARK_YELLOW='\033[33m'
export DARK_BLUE='\033[34m'
export DARK_MAGENTA='\033[35m'
export DARK_CYAN='\033[36m'

# Background Colors
export BG_BLACK='\033[40m'
export BG_RED='\033[41m'
export BG_GREEN='\033[42m'
export BG_YELLOW='\033[43m'
export BG_BLUE='\033[44m'
export BG_MAGENTA='\033[45m'
export BG_CYAN='\033[46m'
export BG_WHITE='\033[47m'

# Legacy aliases (for backward compatibility)
export NC="${RESET}"

# ══════════════════════════════════════════════════════════════════════════════
# SYMBOLS & ICONS
# ══════════════════════════════════════════════════════════════════════════════
# Status Icons
export ICON_SUCCESS="✓"
export ICON_FAILURE="✗"
export ICON_WARNING="⚠"
export ICON_INFO="ℹ"
export ICON_PENDING="○"
export ICON_RUNNING="●"
export ICON_ARROW="→"
export ICON_BULLET="▸"
export ICON_STAR="★"
export ICON_LIGHTNING="⚡"
export ICON_GEAR="⚙"
export ICON_LOCK="🔒"
export ICON_UNLOCK="🔓"

# Emoji Status (for richer output)
export EMOJI_SUCCESS="✅"
export EMOJI_FAILURE="❌"
export EMOJI_WARNING="⚠️"
export EMOJI_INFO="ℹ️"
export EMOJI_ROCKET="🚀"
export EMOJI_PACKAGE="📦"
export EMOJI_CLOCK="⏳"
export EMOJI_CHECK="✔️"
export EMOJI_FIRE="🔥"
export EMOJI_SPARKLES="✨"
export EMOJI_LINK="🔗"
export EMOJI_KEY="🔑"
export EMOJI_FOLDER="📁"
export EMOJI_FILE="📄"
export EMOJI_SEARCH="🔍"
export EMOJI_TOOLS="🔧"
export EMOJI_CHART="📊"
export EMOJI_GLOBE="🌐"
export EMOJI_DATABASE="🗄️"
export EMOJI_SHIELD="🛡️"
export EMOJI_PARTY="🎉"

# Box Drawing Characters
export BOX_H="━"
export BOX_V="┃"
export BOX_TL="┏"
export BOX_TR="┓"
export BOX_BL="┗"
export BOX_BR="┛"
export BOX_VL="┣"
export BOX_VR="┫"
export BOX_HT="┳"
export BOX_HB="┻"
export BOX_X="╋"
export TREE_BRANCH="┣━"
export TREE_LAST="┗━"
export TREE_CONT="┃"

# ══════════════════════════════════════════════════════════════════════════════
# PATH RESOLUTION
# ══════════════════════════════════════════════════════════════════════════════

# Find the project root by looking for Taskfile.yaml
_find_project_root() {
  local dir="${1:-$(pwd)}"
  while [[ "$dir" != "/" ]]; do
    if [[ -f "$dir/Taskfile.yaml" ]] && [[ -d "$dir/infrastructure" ]]; then
      echo "$dir"
      return 0
    fi
    dir="$(dirname "$dir")"
  done
  return 1
}

# Script directory detection
if [[ -n "${BASH_SOURCE[0]:-}" ]]; then
  _LIB_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
else
  _LIB_DIR="$(pwd)"
fi

# Export commonly used paths
export LIB_DIR="${_LIB_DIR}"
export PROJECT_ROOT="${PROJECT_ROOT:-$(_find_project_root "$_LIB_DIR" || echo "$(cd "$_LIB_DIR/../.." && pwd)")}"
export SCRIPT_DIR="${SCRIPT_DIR:-$(cd "$_LIB_DIR/.." && pwd)}"

# ══════════════════════════════════════════════════════════════════════════════
# CONFIGURATION DEFAULTS
# ══════════════════════════════════════════════════════════════════════════════
export TALOS_NODE="${TALOS_NODE:-192.168.1.54}"
export DOMAIN="${DOMAIN:-talos00}"
export CLUSTER_NAME="${CLUSTER_NAME:-homelab-single}"
export TALOSCONFIG="${TALOSCONFIG:-${PROJECT_ROOT}/configs/talosconfig}"
export OUTPUT_DIR="${OUTPUT_DIR:-${PROJECT_ROOT}/.output}"

# Kubeconfig search order
_find_kubeconfig() {
  if [[ -n "${KUBECONFIG:-}" ]] && [[ -f "$KUBECONFIG" ]]; then
    echo "$KUBECONFIG"
  elif [[ -f "${OUTPUT_DIR}/kubeconfig" ]]; then
    echo "${OUTPUT_DIR}/kubeconfig"
  elif [[ -f "${HOME}/.kube/config" ]]; then
    echo "${HOME}/.kube/config"
  else
    echo ""
  fi
}

export KUBECONFIG="${KUBECONFIG:-$(_find_kubeconfig)}"

# ══════════════════════════════════════════════════════════════════════════════
# LOGGING FUNCTIONS
# ══════════════════════════════════════════════════════════════════════════════

# Print a message with a colored prefix
# Usage: log_msg "PREFIX" "COLOR" "message"
log_msg() {
  local prefix="$1"
  local color="$2"
  shift 2
  echo -e "${color}${prefix}${RESET} $*"
}

# Standard log levels
log_info() {
  log_msg "${ICON_INFO}" "${BLUE}" "$@"
}

log_success() {
  log_msg "${ICON_SUCCESS}" "${GREEN}" "$@"
}

log_warning() {
  log_msg "${ICON_WARNING}" "${YELLOW}" "$@"
}

log_error() {
  log_msg "${ICON_FAILURE}" "${RED}" "$@"
}

log_debug() {
  if [[ "${DEBUG:-false}" == "true" ]]; then
    log_msg "DEBUG" "${DIM}" "$@"
  fi
}

# Shorthand aliases
info() { log_info "$@"; }
success() { log_success "$@"; }
warn() { log_warning "$@"; }
error() { log_error "$@"; }
debug() { log_debug "$@"; }

# Step logging for multi-step operations
# Usage: log_step 1 "Description"
log_step() {
  local step_num="$1"
  shift
  echo ""
  echo -e "${CYAN}${BOLD}[${step_num}]${RESET} ${BOLD}$*${RESET}"
}

# Print a dimmed note
log_note() {
  echo -e "    ${DIM}$*${RESET}"
}

# ══════════════════════════════════════════════════════════════════════════════
# HEADER & BANNER FUNCTIONS
# ══════════════════════════════════════════════════════════════════════════════

# Print a synthwave-style header box
# Usage: print_header "TITLE" ["subtitle"]
print_header() {
  local title="$1"
  local subtitle="${2:-}"
  local width=70

  echo ""
  echo -e "${CYAN}${BOLD}"
  printf '%s' "${BOX_TL}"
  printf '%*s' "$width" '' | tr ' ' "${BOX_H}"
  printf '%s\n' "${BOX_TR}"

  printf '%s' "${BOX_V}"
  printf " %-$((width - 1))s" "$title"
  printf '%s\n' "${BOX_V}"

  if [[ -n "$subtitle" ]]; then
    printf '%s' "${BOX_V}"
    printf " ${DIM}%-$((width - 1))s${BOLD}" "$subtitle"
    printf '%s\n' "${BOX_V}"
  fi

  printf '%s' "${BOX_BL}"
  printf '%*s' "$width" '' | tr ' ' "${BOX_H}"
  printf '%s\n' "${BOX_BR}"
  echo -e "${RESET}"
}

# Print a simple section divider
# Usage: print_divider ["character"]
print_divider() {
  local char="${1:-═}"
  local width=70
  echo -e "${DIM}"
  printf '%*s\n' "$width" '' | tr ' ' "$char"
  echo -e "${RESET}"
}

# Print a section header
# Usage: print_section "SECTION NAME"
print_section() {
  local title="$1"
  echo -e "${MAGENTA}${BOLD}${ICON_BULLET} ${title}${RESET}"
}

# Print a subsection header
# Usage: print_subsection "Subsection Name"
print_subsection() {
  local title="$1"
  echo -e "  ${CYAN}${title}${RESET}"
}

# Print an ASCII art banner (for dashboards)
# Usage: print_banner "text" ["color"]
print_banner() {
  local text="$1"
  local color="${2:-${CYAN}}"
  echo -e "${color}${BOLD}"
  echo "$text"
  echo -e "${RESET}"
}

# ══════════════════════════════════════════════════════════════════════════════
# STATUS INDICATORS
# ══════════════════════════════════════════════════════════════════════════════

# Print a status indicator
# Usage: print_status "Running" "true" -> [✓] (green)
# Usage: print_status "Pending" "false" -> [⚠] (yellow)
# Usage: print_status "" "" -> [✗] (red)
print_status() {
  local status="${1:-}"
  local ready="${2:-false}"

  if [[ "$status" == "Running" ]] && [[ "$ready" == "true" ]]; then
    echo -e "${GREEN}[${ICON_SUCCESS}]${RESET}"
  elif [[ -z "$status" ]] || [[ "$status" == "null" ]] || [[ "$status" == "NotFound" ]]; then
    echo -e "${RED}[${ICON_FAILURE}]${RESET}"
  else
    echo -e "${YELLOW}[${ICON_WARNING}]${RESET}"
  fi
}

# Print inline status with label
# Usage: print_status_inline "Pod" "Running" "true"
print_status_inline() {
  local label="$1"
  local status="${2:-}"
  local ready="${3:-false}"
  local indicator
  indicator=$(print_status "$status" "$ready")
  echo -e "${indicator} ${label}"
}

# ══════════════════════════════════════════════════════════════════════════════
# PROGRESS & SPINNERS
# ══════════════════════════════════════════════════════════════════════════════

# Print a progress bar
# Usage: print_progress 75 100
print_progress() {
  local current="$1"
  local total="$2"
  local width="${3:-40}"
  local percent=$((current * 100 / total))
  local filled=$((width * current / total))
  local empty=$((width - filled))

  printf "\r${CYAN}["
  printf '%*s' "$filled" '' | tr ' ' '█'
  printf '%*s' "$empty" '' | tr ' ' '░'
  printf "] ${percent}%%${RESET}"
}

# Simple spinner for background tasks
# Usage: start_spinner "Loading..."; do_work; stop_spinner
_SPINNER_PID=""
_SPINNER_MSG=""

start_spinner() {
  _SPINNER_MSG="${1:-Loading}"
  (
    local frames=('⠋' '⠙' '⠹' '⠸' '⠼' '⠴' '⠦' '⠧' '⠇' '⠏')
    local i=0
    while true; do
      printf "\r${CYAN}${frames[$i]}${RESET} ${_SPINNER_MSG}..."
      i=$(((i + 1) % ${#frames[@]}))
      sleep 0.1
    done
  ) &
  _SPINNER_PID=$!
  disown
}

stop_spinner() {
  local status="${1:-success}"
  if [[ -n "$_SPINNER_PID" ]]; then
    kill "$_SPINNER_PID" 2>/dev/null || true
    wait "$_SPINNER_PID" 2>/dev/null || true
    _SPINNER_PID=""
  fi

  printf "\r"
  if [[ "$status" == "success" ]]; then
    echo -e "${GREEN}${ICON_SUCCESS}${RESET} ${_SPINNER_MSG}... done"
  elif [[ "$status" == "failure" ]]; then
    echo -e "${RED}${ICON_FAILURE}${RESET} ${_SPINNER_MSG}... failed"
  else
    echo -e "${YELLOW}${ICON_WARNING}${RESET} ${_SPINNER_MSG}... $status"
  fi
}

# ══════════════════════════════════════════════════════════════════════════════
# TREE-STYLE OUTPUT
# ══════════════════════════════════════════════════════════════════════════════

# Print a tree item
# Usage: print_tree_item "name" "status" "url" "is_last" ["extra"]
print_tree_item() {
  local name="$1"
  local status="${2:-}"
  local url="${3:-}"
  local is_last="${4:-false}"
  local extra="${5:-}"

  local branch="${TREE_BRANCH}"
  [[ "$is_last" == "true" ]] && branch="${TREE_LAST}"

  local status_indicator
  status_indicator=$(print_status "$status" "true")

  local line="  ${BOLD}${branch} ${name}${RESET} ${status_indicator}"

  if [[ -n "$url" ]]; then
    line+=" ${DIM}${ICON_ARROW}${RESET} ${CYAN}${url}${RESET}"
  fi

  if [[ -n "$extra" ]]; then
    line+=" ${DIM}│${RESET} ${extra}"
  fi

  echo -e "$line"
}

# Print a tree sub-item (indented under a tree item)
# Usage: print_tree_subitem "text" "is_parent_last"
print_tree_subitem() {
  local text="$1"
  local is_parent_last="${2:-false}"

  local cont="${TREE_CONT}"
  [[ "$is_parent_last" == "true" ]] && cont=" "

  echo -e "  ${cont}    ${DIM}${text}${RESET}"
}

# ══════════════════════════════════════════════════════════════════════════════
# TABLES & FORMATTED OUTPUT
# ══════════════════════════════════════════════════════════════════════════════

# Print a key-value pair
# Usage: print_kv "Key" "Value"
print_kv() {
  local key="$1"
  local value="$2"
  local width="${3:-15}"
  printf "  ${CYAN}%-${width}s${RESET} │ %s\n" "$key" "$value"
}

# Print a table header
# Usage: print_table_header "Col1" "Col2" "Col3"
print_table_header() {
  local sep="  "
  echo -e "${BOLD}"
  for col in "$@"; do
    printf "%-15s" "$col"
  done
  echo -e "${RESET}"
  echo -e "${DIM}$(printf '─%.0s' {1..60})${RESET}"
}

# ══════════════════════════════════════════════════════════════════════════════
# PREREQUISITE CHECKS
# ══════════════════════════════════════════════════════════════════════════════

# Check if a command exists
# Usage: require_cmd "kubectl" || exit 1
require_cmd() {
  local cmd="$1"
  local msg="${2:-$cmd is required but not installed}"
  if ! command -v "$cmd" &>/dev/null; then
    log_error "$msg"
    return 1
  fi
  return 0
}

# Check multiple commands
# Usage: require_cmds kubectl helm jq || exit 1
require_cmds() {
  local missing=()
  for cmd in "$@"; do
    if ! command -v "$cmd" &>/dev/null; then
      missing+=("$cmd")
    fi
  done

  if [[ ${#missing[@]} -gt 0 ]]; then
    log_error "Missing required commands: ${missing[*]}"
    return 1
  fi
  return 0
}

# Check if cluster is accessible
# Usage: require_cluster || exit 1
require_cluster() {
  if ! kubectl cluster-info &>/dev/null; then
    log_error "Cannot connect to Kubernetes cluster"
    log_note "Make sure your kubeconfig is correct: $KUBECONFIG"
    log_note "Or run: task kubeconfig-merge"
    return 1
  fi
  return 0
}

# Check if Talos is accessible
# Usage: require_talos || exit 1
require_talos() {
  if ! talosctl --talosconfig "$TALOSCONFIG" --nodes "$TALOS_NODE" version &>/dev/null; then
    log_error "Cannot connect to Talos node: $TALOS_NODE"
    log_note "Check that the node is running and talosconfig is correct"
    return 1
  fi
  return 0
}

# Check if namespace exists
# Usage: require_namespace "monitoring" || exit 1
require_namespace() {
  local namespace="$1"
  if ! kubectl get namespace "$namespace" &>/dev/null; then
    log_error "Namespace '$namespace' not found"
    return 1
  fi
  return 0
}

# ══════════════════════════════════════════════════════════════════════════════
# KUBERNETES HELPERS
# ══════════════════════════════════════════════════════════════════════════════

# Wait for a resource to be ready
# Usage: wait_for_resource "pod -l app=nginx" "default" 300
wait_for_resource() {
  local resource="$1"
  local namespace="${2:-default}"
  local timeout="${3:-300}"

  log_info "Waiting for $resource in $namespace (timeout: ${timeout}s)..."

  if kubectl wait --for=condition=ready "$resource" -n "$namespace" --timeout="${timeout}s" 2>/dev/null; then
    log_success "$resource is ready"
    return 0
  else
    log_warning "Timeout waiting for $resource"
    return 1
  fi
}

# Apply kustomize directory with dry-run check
# Usage: apply_kustomize "infrastructure/base/monitoring/"
apply_kustomize() {
  local path="$1"
  local dry_run="${2:-false}"

  if [[ "$dry_run" == "true" ]]; then
    log_info "Dry-run: kubectl apply -k $path"
    kubectl apply -k "$path" --dry-run=client
  else
    log_info "Applying: $path"
    kubectl apply -k "$path"
  fi
}

# Get secret data (base64 decoded)
# Usage: get_secret "namespace" "secret-name" "key"
get_secret() {
  local namespace="$1"
  local secret_name="$2"
  local key="$3"
  kubectl get secret "$secret_name" -n "$namespace" -o jsonpath="{.data.$key}" 2>/dev/null | base64 -d 2>/dev/null
}

# ══════════════════════════════════════════════════════════════════════════════
# HELM HELPERS
# ══════════════════════════════════════════════════════════════════════════════

# Add helm repo if not already added
# Usage: helm_repo_add "prometheus-community" "https://prometheus-community.github.io/helm-charts"
helm_repo_add() {
  local name="$1"
  local url="$2"

  if helm repo list 2>/dev/null | grep -q "^${name}"; then
    log_debug "Helm repo '$name' already exists"
  else
    log_info "Adding Helm repo: $name"
    helm repo add "$name" "$url"
  fi
}

# Install or upgrade a helm release
# Usage: helm_install "release-name" "chart" "namespace" "values.yaml"
helm_install() {
  local release="$1"
  local chart="$2"
  local namespace="$3"
  local values="${4:-}"
  local timeout="${5:-10m}"

  local cmd="helm upgrade --install $release $chart -n $namespace --create-namespace --wait --timeout $timeout"

  if [[ -n "$values" ]] && [[ -f "$values" ]]; then
    cmd+=" -f $values"
  fi

  log_info "Installing Helm release: $release"
  eval "$cmd"
}

# ══════════════════════════════════════════════════════════════════════════════
# USER INTERACTION
# ══════════════════════════════════════════════════════════════════════════════

# Ask for confirmation
# Usage: confirm "Continue?" || exit 0
confirm() {
  local prompt="${1:-Continue?}"
  local default="${2:-n}"

  local choices="y/N"
  [[ "$default" == "y" ]] && choices="Y/n"

  read -p "$(echo -e "${YELLOW}${prompt}${RESET} (${choices}) ")" -n 1 -r
  echo

  if [[ "$default" == "y" ]]; then
    [[ ! $REPLY =~ ^[Nn]$ ]]
  else
    [[ $REPLY =~ ^[Yy]$ ]]
  fi
}

# Ask for a value with default
# Usage: ask "Enter port" "8080"
ask() {
  local prompt="$1"
  local default="${2:-}"
  local value

  if [[ -n "$default" ]]; then
    read -p "$(echo -e "${CYAN}${prompt}${RESET} [${default}]: ")" value
    echo "${value:-$default}"
  else
    read -p "$(echo -e "${CYAN}${prompt}${RESET}: ")" value
    echo "$value"
  fi
}

# Ask for password (no echo)
# Usage: ask_password "Enter password"
ask_password() {
  local prompt="$1"
  local value
  read -sp "$(echo -e "${CYAN}${prompt}${RESET}: ")" value
  echo
  echo "$value"
}

# ══════════════════════════════════════════════════════════════════════════════
# UTILITY FUNCTIONS
# ══════════════════════════════════════════════════════════════════════════════

# Create a timestamped backup of a file
# Usage: backup_file "/path/to/file"
backup_file() {
  local file="$1"
  if [[ -f "$file" ]]; then
    local backup="${file}.backup.$(date +%Y%m%d-%H%M%S)"
    cp "$file" "$backup"
    log_info "Backup created: $backup"
    echo "$backup"
  fi
}

# Ensure a directory exists
# Usage: ensure_dir "/path/to/dir"
ensure_dir() {
  local dir="$1"
  if [[ ! -d "$dir" ]]; then
    mkdir -p "$dir"
    log_debug "Created directory: $dir"
  fi
}

# Check if running in CI
is_ci() {
  [[ -n "${CI:-}" ]] || [[ -n "${GITHUB_ACTIONS:-}" ]] || [[ -n "${GITLAB_CI:-}" ]]
}

# Get elapsed time since a timestamp
# Usage: start=$(date +%s); ... ; elapsed_time $start
elapsed_time() {
  local start="$1"
  local end="${2:-$(date +%s)}"
  local elapsed=$((end - start))

  if [[ $elapsed -lt 60 ]]; then
    echo "${elapsed}s"
  elif [[ $elapsed -lt 3600 ]]; then
    echo "$((elapsed / 60))m $((elapsed % 60))s"
  else
    echo "$((elapsed / 3600))h $((elapsed % 3600 / 60))m"
  fi
}

# ══════════════════════════════════════════════════════════════════════════════
# RETRY LOGIC
# ══════════════════════════════════════════════════════════════════════════════

# Retry a command with exponential backoff
# Usage: retry 5 10 "kubectl get nodes"
retry() {
  local max_attempts="$1"
  local delay="$2"
  shift 2
  local cmd="$*"

  local attempt=1
  while [[ $attempt -le $max_attempts ]]; do
    log_info "Attempt $attempt/$max_attempts: $cmd"

    if eval "$cmd"; then
      log_success "Command succeeded on attempt $attempt"
      return 0
    fi

    if [[ $attempt -lt $max_attempts ]]; then
      log_warning "Command failed, retrying in ${delay}s..."
      sleep "$delay"
      delay=$((delay * 2))  # Exponential backoff
    fi

    attempt=$((attempt + 1))
  done

  log_error "Command failed after $max_attempts attempts"
  return 1
}

# ══════════════════════════════════════════════════════════════════════════════
# CLEANUP & EXIT HANDLING
# ══════════════════════════════════════════════════════════════════════════════

# Array of cleanup functions
_CLEANUP_FUNCTIONS=()

# Register a cleanup function
# Usage: register_cleanup "rm -rf /tmp/mydir"
register_cleanup() {
  _CLEANUP_FUNCTIONS+=("$1")
}

# Run all cleanup functions
_run_cleanup() {
  for func in "${_CLEANUP_FUNCTIONS[@]}"; do
    eval "$func" 2>/dev/null || true
  done
}

# Set up trap for cleanup (call this at script start if needed)
setup_cleanup_trap() {
  trap _run_cleanup EXIT
}

# ══════════════════════════════════════════════════════════════════════════════
# SCRIPT INITIALIZATION
# ══════════════════════════════════════════════════════════════════════════════

# Initialize script environment
# Usage: init_script "My Script" "Description"
init_script() {
  local name="${1:-Script}"
  local description="${2:-}"

  # Change to project root
  cd "$PROJECT_ROOT"

  # Ensure output directory exists
  ensure_dir "$OUTPUT_DIR"

  # Print header if not in quiet mode
  if [[ "${QUIET:-false}" != "true" ]]; then
    if [[ -n "$description" ]]; then
      print_header "$name" "$description"
    else
      print_header "$name"
    fi
  fi
}

# Quick init for scripts that just need basic setup
# Usage: quick_init
quick_init() {
  cd "$PROJECT_ROOT"
  ensure_dir "$OUTPUT_DIR"
}

# ══════════════════════════════════════════════════════════════════════════════
# SUMMARY & REPORTING
# ══════════════════════════════════════════════════════════════════════════════

# Print a summary box at the end of a script
# Usage: print_summary "Success" "message1" "message2"
print_summary() {
  local status="$1"
  shift

  echo ""
  print_divider

  if [[ "$status" == "success" ]]; then
    echo -e "${GREEN}${BOLD}${EMOJI_SUCCESS} Complete!${RESET}"
  elif [[ "$status" == "warning" ]]; then
    echo -e "${YELLOW}${BOLD}${EMOJI_WARNING} Completed with warnings${RESET}"
  else
    echo -e "${RED}${BOLD}${EMOJI_FAILURE} Failed${RESET}"
  fi

  echo ""
  for msg in "$@"; do
    echo -e "  ${msg}"
  done
  echo ""
}

# Print next steps
# Usage: print_next_steps "Run this" "Then that" "Finally this"
print_next_steps() {
  echo -e "${CYAN}${BOLD}Next Steps:${RESET}"
  local i=1
  for step in "$@"; do
    echo -e "  ${i}. ${step}"
    i=$((i + 1))
  done
  echo ""
}

# Print URLs section
# Usage: print_urls "Grafana|http://grafana.talos00" "Prometheus|http://prometheus.talos00"
print_urls() {
  print_section "Access URLs"
  echo -e "  ${DIM}(Requires /etc/hosts entries for *.${DOMAIN})${RESET}"
  echo ""

  for entry in "$@"; do
    local name="${entry%%|*}"
    local url="${entry#*|}"
    printf "  ${CYAN}%-15s${RESET} ${ICON_ARROW} %s\n" "$name" "$url"
  done
  echo ""
}

# Print credentials section
# Usage: print_credentials "Grafana|admin:password" "ArgoCD|admin:secret"
print_credentials() {
  print_section "Credentials"
  echo ""

  for entry in "$@"; do
    local name="${entry%%|*}"
    local creds="${entry#*|}"
    printf "  ${CYAN}%-15s${RESET} │ ${YELLOW}%s${RESET}\n" "$name" "$creds"
  done
  echo ""
}
