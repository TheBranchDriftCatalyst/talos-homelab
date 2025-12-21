#!/usr/bin/env bash
# Generic Namespace Dashboard - Node-centric cluster status display
# Uses gum for styled output with full credential visibility
#
# Usage:
#   ./namespace-dashboard.sh [namespace]     # Show dashboard for namespace
#   ./namespace-dashboard.sh                 # Interactive namespace selection
#   ./namespace-dashboard.sh --list          # List all namespaces
#
# shellcheck disable=SC2016,SC2034

set -euo pipefail

# Get script directory and source common library
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

# shellcheck source=lib/dashboard-common.sh
source "${SCRIPT_DIR}/lib/dashboard-common.sh"

# Unset color variables that conflict with gum flags
unset BOLD FAINT ITALIC UNDERLINE

# ============================================================================
# Configuration
# ============================================================================
NAMESPACE="${1:-}"
LIST_MODE=false
export PLAIN_MODE=false  # Export for use in common lib functions

# Auto-detect non-TTY (e.g., running in Tilt, piped output)
if [[ ! -t 1 ]]; then
  export PLAIN_MODE=true
fi

# Parse arguments
while [[ $# -gt 0 ]]; do
  case $1 in
    --list | -l)
      LIST_MODE=true
      shift
      ;;
    --plain | -p)
      export PLAIN_MODE=true
      shift
      ;;
    --help | -h)
      echo "Usage: $0 [namespace] [options]"
      echo ""
      echo "Options:"
      echo "  --list, -l    List all namespaces"
      echo "  --plain, -p   Plain text output (no gum styling)"
      echo "  --help, -h    Show this help"
      echo ""
      echo "Examples:"
      echo "  $0 media          # Show media namespace dashboard"
      echo "  $0                # Interactive namespace selection"
      echo "  $0 --list         # List all namespaces"
      echo "  $0 media --plain  # Plain output for scripts/Tilt"
      exit 0
      ;;
    -*)
      shift
      ;;
    *)
      NAMESPACE="$1"
      shift
      ;;
  esac
done

# Check for gum (only required for interactive mode)
if [[ "$PLAIN_MODE" != "true" ]]; then
  require_cmd "gum" "gum is required for styled output (brew install gum), or use --plain"
fi

# ============================================================================
# Styling helpers (gum or plain text)
# ============================================================================

# Print styled header
gum_header() {
  local title=$1
  if [[ "$PLAIN_MODE" == "true" ]]; then
    echo ""
    echo "═══════════════════════════════════════════════════════════"
    echo "  $title"
    echo "═══════════════════════════════════════════════════════════"
    echo ""
  else
    gum style \
      --foreground 212 --border-foreground 212 --border double \
      --align center --width 60 --margin "1 2" --padding "1 2" \
      "$title"
  fi
}

# Print section header
gum_section() {
  local title=$1
  if [[ "$PLAIN_MODE" == "true" ]]; then
    echo "▸ $title"
  else
    gum style --foreground 141 --bold "▸ $title"
  fi
}

# Print success status
gum_success() {
  if [[ "$PLAIN_MODE" == "true" ]]; then
    echo "✓ $1"
  else
    gum style --foreground 120 "✓ $1"
  fi
}

# Print warning
gum_warn() {
  if [[ "$PLAIN_MODE" == "true" ]]; then
    echo "⚠ $1"
  else
    gum style --foreground 220 "⚠ $1"
  fi
}

# Print error
gum_error() {
  if [[ "$PLAIN_MODE" == "true" ]]; then
    echo "✗ $1"
  else
    gum style --foreground 196 "✗ $1"
  fi
}

# Print dim text
gum_dim() {
  if [[ "$PLAIN_MODE" == "true" ]]; then
    echo "$1"
  else
    gum style --foreground 245 "$1"
  fi
}

# Print info
gum_info() {
  if [[ "$PLAIN_MODE" == "true" ]]; then
    echo "$1"
  else
    gum style --foreground 117 "$1"
  fi
}

# Spinner wrapper (no-op in plain mode)
gum_spin() {
  if [[ "$PLAIN_MODE" == "true" ]]; then
    # Just run the command silently
    shift  # remove --spinner
    shift  # remove spinner type
    shift  # remove --title
    local title="$1"
    shift  # remove title
    shift  # remove --
    "$@" 2>/dev/null || true
  else
    gum spin "$@"
  fi
}

# ============================================================================
# Shared PVC tracking
# ============================================================================
declare -A SHARED_PVC_COUNTS

# ============================================================================
# Service display with full credentials
# ============================================================================

# Get pod status checking multiple label patterns
get_pod_status_smart() {
  local name=$1
  local result

  # Try app label
  result=$(jq -r ".items[] | select(.metadata.labels.app == \"$name\") | .status.phase" "$CACHE_DIR/pods.json" 2>/dev/null | head -1)
  [[ -n "$result" ]] && echo "$result" && return

  # Try app.kubernetes.io/name
  result=$(jq -r ".items[] | select(.metadata.labels[\"app.kubernetes.io/name\"] == \"$name\") | .status.phase" "$CACHE_DIR/pods.json" 2>/dev/null | head -1)
  [[ -n "$result" ]] && echo "$result" && return

  # Try app.kubernetes.io/instance
  result=$(jq -r ".items[] | select(.metadata.labels[\"app.kubernetes.io/instance\"] == \"$name\") | .status.phase" "$CACHE_DIR/pods.json" 2>/dev/null | head -1)
  [[ -n "$result" ]] && echo "$result" && return

  # Try matching pod name prefix
  result=$(jq -r ".items[] | select(.metadata.name | startswith(\"$name\")) | .status.phase" "$CACHE_DIR/pods.json" 2>/dev/null | head -1)
  [[ -n "$result" ]] && echo "$result" && return

  echo ""
}

# Get pod ready status checking multiple label patterns
get_pod_ready_smart() {
  local name=$1
  local result

  # Try app label
  result=$(jq -r ".items[] | select(.metadata.labels.app == \"$name\") | .status.containerStatuses[0].ready // false" "$CACHE_DIR/pods.json" 2>/dev/null | head -1)
  [[ -n "$result" ]] && [[ "$result" != "null" ]] && echo "$result" && return

  # Try app.kubernetes.io/name
  result=$(jq -r ".items[] | select(.metadata.labels[\"app.kubernetes.io/name\"] == \"$name\") | .status.containerStatuses[0].ready // false" "$CACHE_DIR/pods.json" 2>/dev/null | head -1)
  [[ -n "$result" ]] && [[ "$result" != "null" ]] && echo "$result" && return

  # Try app.kubernetes.io/instance
  result=$(jq -r ".items[] | select(.metadata.labels[\"app.kubernetes.io/instance\"] == \"$name\") | .status.containerStatuses[0].ready // false" "$CACHE_DIR/pods.json" 2>/dev/null | head -1)
  [[ -n "$result" ]] && [[ "$result" != "null" ]] && echo "$result" && return

  # Try matching pod name prefix
  result=$(jq -r ".items[] | select(.metadata.name | startswith(\"$name\")) | .status.containerStatuses[0].ready // false" "$CACHE_DIR/pods.json" 2>/dev/null | head -1)
  [[ -n "$result" ]] && [[ "$result" != "null" ]] && echo "$result" && return

  echo "false"
}

# Style helper - applies gum style or plain text
style_text() {
  local color=$1
  local text=$2
  local bold=${3:-false}
  if [[ "$PLAIN_MODE" == "true" ]]; then
    echo "$text"
  elif [[ "$bold" == "true" ]]; then
    gum style --foreground "$color" --bold "$text"
  else
    gum style --foreground "$color" "$text"
  fi
}

# Print a service with full credentials nested underneath
print_service_full() {
  local name=$1
  local is_last=${2:-false}
  local node=$3
  local namespace=$4

  local status ready ingress_url
  status=$(get_pod_status_smart "$name")
  ready=$(get_pod_ready_smart "$name")
  ingress_url=$(get_ingress_url "$name")

  [[ -z "$status" ]] && status="NotFound"

  # Status indicator
  local status_icon="[?]"
  local status_color="245"
  case "$status" in
    Running)
      if [[ "$ready" == "true" ]]; then
        status_icon="[✓]"
        status_color="120"
      else
        status_icon="[○]"
        status_color="220"
      fi
      ;;
    Pending) status_icon="[○]"; status_color="220" ;;
    Failed|Error) status_icon="[✗]"; status_color="196" ;;
  esac

  # Tree characters
  local branch="┣━"
  local cont="┃"
  [[ "$is_last" == "true" ]] && branch="┗━" && cont=" "

  # Main service line
  local status_styled name_styled url_styled=""
  if [[ "$PLAIN_MODE" == "true" ]]; then
    status_styled="$status_icon"
    name_styled="$name"
    [[ -n "$ingress_url" ]] && url_styled="→ $ingress_url"
  else
    status_styled=$(gum style --foreground "$status_color" "$status_icon")
    name_styled=$(gum style --bold "$name")
    [[ -n "$ingress_url" ]] && url_styled=$(gum style --foreground 117 "→ $ingress_url")
  fi

  echo " $branch $name_styled $status_styled $url_styled"

  # Credentials (fully visible, nested)
  local api_key=""

  # Try common secret patterns for API keys
  for secret_pattern in "${name}-api-key" "${name^^}_API_KEY" "api-key" "apikey"; do
    # Try arr-api-keys secret
    api_key=$(jq -r ".items[] | select(.metadata.name == \"arr-api-keys\") | .data[\"${name^^}_API_KEY\"] // empty" "$CACHE_DIR/secrets.json" 2>/dev/null)
    [[ -n "$api_key" ]] && api_key=$(echo "$api_key" | base64 -d 2>/dev/null) && break

    # Try arr-stack-secrets
    api_key=$(jq -r ".items[] | select(.metadata.name == \"arr-stack-secrets\") | .data[\"${name}-api-key\"] // empty" "$CACHE_DIR/secrets.json" 2>/dev/null)
    [[ -n "$api_key" ]] && api_key=$(echo "$api_key" | base64 -d 2>/dev/null) && break

    # Try service-specific secret
    api_key=$(jq -r ".items[] | select(.metadata.name == \"${name}-secret\" or .metadata.name == \"${name}-credentials\") | .data | to_entries[] | select(.key | test(\"api|key|token|password\"; \"i\")) | .value" "$CACHE_DIR/secrets.json" 2>/dev/null | head -1)
    [[ -n "$api_key" ]] && api_key=$(echo "$api_key" | base64 -d 2>/dev/null) && break
  done

  if [[ -n "$api_key" ]]; then
    if [[ "$PLAIN_MODE" == "true" ]]; then
      echo " $cont   apikey: $api_key"
    else
      echo " $cont   $(gum style --foreground 220 "apikey: $api_key")"
    fi
  fi

  # Check for username/password credentials
  local cred_secret
  cred_secret=$(jq -r ".items[] | select(.metadata.name == \"${name}-secret\" or .metadata.name == \"${name}-credentials\") | .metadata.name" "$CACHE_DIR/secrets.json" 2>/dev/null | head -1)
  if [[ -n "$cred_secret" ]]; then
    local username password
    username=$(jq -r ".items[] | select(.metadata.name == \"$cred_secret\") | .data.username // .data.user // .data.POSTGRES_USER // empty" "$CACHE_DIR/secrets.json" 2>/dev/null)
    password=$(jq -r ".items[] | select(.metadata.name == \"$cred_secret\") | .data.password // .data.pass // .data.POSTGRES_PASSWORD // empty" "$CACHE_DIR/secrets.json" 2>/dev/null)

    if [[ -n "$username" ]] && [[ -n "$password" ]]; then
      username=$(echo "$username" | base64 -d 2>/dev/null)
      password=$(echo "$password" | base64 -d 2>/dev/null)
      if [[ "$PLAIN_MODE" == "true" ]]; then
        echo " $cont   user: $username  pass: $password"
      else
        echo " $cont   $(gum style --foreground 220 "user: $username  pass: $password")"
      fi
    fi
  fi

  # ALL PVC volumes - color-coded by sharing
  local all_vols
  all_vols=$(jq -r ".items[] | select(.metadata.name == \"$name\") | .spec.template.spec.volumes[]? | select(.persistentVolumeClaim != null) | .persistentVolumeClaim.claimName" "$CACHE_DIR/deployments.json" 2>/dev/null)

  if [[ -n "$all_vols" ]]; then
    while read -r pvc; do
      [[ -z "$pvc" ]] && continue
      local pvc_info
      pvc_info=$(jq -r ".items[] | select(.metadata.name == \"$pvc\") | .spec.resources.requests.storage + \"|\" + .spec.storageClassName" "$CACHE_DIR/pvcs.json" 2>/dev/null)
      [[ -z "$pvc_info" ]] && continue

      local size sc
      IFS='|' read -r size sc <<< "$pvc_info"
      local sc_short
      sc_short=$(shorten_storageclass "$sc")

      # Color based on sharing
      local share_count="${SHARED_PVC_COUNTS[$pvc]:-1}"
      local vol_icon="●"
      local share_info=""
      if [[ $share_count -gt 1 ]]; then
        vol_icon="◉"
        share_info=" ⟷$share_count"
      fi

      local short_name="${pvc##*-}"
      [[ "$short_name" == "$pvc" ]] && short_name="${pvc}"

      if [[ "$PLAIN_MODE" == "true" ]]; then
        echo " $cont   $vol_icon $short_name ($size) [$sc_short]$share_info"
      else
        local vol_color="120"  # green
        [[ $share_count -gt 1 ]] && vol_color="212"  # magenta
        local vol_styled name_dim size_styled sc_styled share_styled=""
        vol_styled=$(gum style --foreground "$vol_color" "$vol_icon")
        name_dim=$(gum style --foreground 245 "$short_name")
        size_styled=$(gum style --foreground 117 "($size)")
        sc_styled=$(gum style --foreground 245 "[$sc_short]")
        [[ -n "$share_info" ]] && share_styled=$(gum style --foreground 245 "$share_info")
        echo " $cont   $vol_styled $name_dim $size_styled $sc_styled$share_styled"
      fi
    done <<< "$all_vols"
  fi

  # emptyDir volumes
  local empty_vols
  empty_vols=$(jq -r ".items[] | select(.metadata.name == \"$name\") | .spec.template.spec.volumes[]? | select(.emptyDir != null) | .name + \"|\" + (.emptyDir.sizeLimit // \"node-disk\")" "$CACHE_DIR/deployments.json" 2>/dev/null)
  if [[ -n "$empty_vols" ]]; then
    while IFS='|' read -r vol limit; do
      [[ -z "$vol" ]] && continue
      if [[ "$PLAIN_MODE" == "true" ]]; then
        echo " $cont   ◆ $vol ($limit)"
      else
        local cache_styled vol_dim limit_styled
        cache_styled=$(gum style --foreground 117 "◆")
        vol_dim=$(gum style --foreground 245 "$vol")
        limit_styled=$(gum style --foreground 117 "($limit)")
        echo " $cont   $cache_styled $vol_dim $limit_styled"
      fi
    done <<< "$empty_vols"
  fi
}

# Print node section
print_node_section_gum() {
  local node=$1
  local services=$2
  local disk_info="${3:-}"
  local namespace=$4

  # Disk usage bar
  local disk_display=""
  if [[ -n "$disk_info" ]]; then
    local used avail total percent
    IFS='|' read -r used avail total percent <<< "$disk_info"
    local pct="${percent%\%}"

    # Build simple bar
    local bar_width=12
    local filled=$((pct * bar_width / 100))
    local empty=$((bar_width - filled))
    local bar=""
    for ((i=0; i<filled; i++)); do bar+="█"; done
    for ((i=0; i<empty; i++)); do bar+="░"; done

    if [[ "$PLAIN_MODE" == "true" ]]; then
      disk_display=" $bar ${pct}% $used/$total"
    else
      local bar_color="120"
      [[ $pct -ge 70 ]] && bar_color="220"
      [[ $pct -ge 90 ]] && bar_color="196"
      local bar_styled
      bar_styled=$(gum style --foreground "$bar_color" "$bar")
      disk_display=" $bar_styled ${pct}% $(gum style --foreground 117 "$used")/$total"
    fi
  fi

  # Count services
  local svc_count
  svc_count=$(echo "$services" | wc -l | tr -d ' ')

  # Node header
  if [[ "$PLAIN_MODE" == "true" ]]; then
    echo "▸ $node ($svc_count)$disk_display"
  else
    local node_styled count_styled
    node_styled=$(gum style --foreground 212 --bold "▸ $node")
    count_styled=$(gum style --foreground 245 "($svc_count)")
    echo "$node_styled $count_styled$disk_display"
  fi

  # Print each service
  local i=0
  local total_svcs
  total_svcs=$(echo "$services" | wc -l | tr -d ' ')
  while read -r svc; do
    [[ -z "$svc" ]] && continue
    i=$((i + 1))
    local is_last="false"
    [[ $i -eq $total_svcs ]] && is_last="true"
    print_service_full "$svc" "$is_last" "$node" "$namespace"
  done <<< "$services"
}

# ============================================================================
# Main dashboard
# ============================================================================
main() {
  # Initialize
  dashboard_init

  # List mode
  if [[ "$LIST_MODE" == "true" ]]; then
    echo "Available namespaces:"
    kubectl get namespaces -o jsonpath='{range .items[*]}{.metadata.name}{"\n"}{end}' | sort
    exit 0
  fi

  # Interactive namespace selection if not provided
  if [[ -z "$NAMESPACE" ]]; then
    if [[ "$PLAIN_MODE" == "true" ]]; then
      echo "Error: Namespace required in plain mode"
      echo "Usage: $0 <namespace> --plain"
      exit 1
    fi
    local namespaces
    namespaces=$(kubectl get namespaces -o jsonpath='{range .items[*]}{.metadata.name}{"\n"}{end}' | sort)
    NAMESPACE=$(echo "$namespaces" | gum choose --header "Select namespace:")
    [[ -z "$NAMESPACE" ]] && exit 0
  fi

  # Only clear in interactive mode
  [[ "$PLAIN_MODE" != "true" ]] && clear

  # Header
  gum_header "📦 $NAMESPACE"

  # Check if namespace exists
  if ! namespace_exists "$NAMESPACE"; then
    gum_error "Namespace '$NAMESPACE' not found"
    exit 1
  fi

  # Fetch data (with or without spinner)
  if [[ "$PLAIN_MODE" == "true" ]]; then
    fetch_namespace_data "$NAMESPACE"
    fetch_cluster_data
  else
    gum spin --spinner dot --title "Loading namespace data..." -- sleep 0.1
    fetch_namespace_data "$NAMESPACE"
    gum spin --spinner dot --title "Loading cluster data..." -- sleep 0.1
    fetch_cluster_data
  fi

  # Get all nodes
  local nodes_str
  nodes_str=$(get_all_nodes)

  if [[ -z "$nodes_str" ]]; then
    gum_warn "No running pods found in namespace '$NAMESPACE'"
    exit 0
  fi

  local -a NODES_ARRAY=()
  while read -r node; do
    [[ -n "$node" ]] && NODES_ARRAY+=("$node")
  done <<< "$nodes_str"

  # Pre-compute shared PVC counts
  if [[ "$PLAIN_MODE" != "true" ]]; then
    gum spin --spinner dot --title "Analyzing volumes..." -- sleep 0.1
  fi
  for node in "${NODES_ARRAY[@]}"; do
    local services
    services=$(get_deployments_on_node "$node")
    while read -r svc; do
      [[ -z "$svc" ]] && continue
      local pvcs
      pvcs=$(jq -r ".items[] | select(.metadata.name == \"$svc\") | .spec.template.spec.volumes[]? | select(.persistentVolumeClaim != null) | .persistentVolumeClaim.claimName" "$CACHE_DIR/deployments.json" 2>/dev/null)
      while read -r pvc; do
        [[ -z "$pvc" ]] && continue
        SHARED_PVC_COUNTS[$pvc]=$((${SHARED_PVC_COUNTS[$pvc]:-0} + 1))
      done <<< "$pvcs"
    done <<< "$services"
  done

  # Pre-fetch node disk usage
  if [[ "$PLAIN_MODE" != "true" ]]; then
    gum spin --spinner dot --title "Fetching disk usage..." -- sleep 0.1
  fi
  declare -A NODE_DISK_INFO
  for node in "${NODES_ARRAY[@]}"; do
    NODE_DISK_INFO["$node"]=$(get_node_disk_usage "$node" "$NAMESPACE" 2>/dev/null || true)
  done

  echo ""

  # Legend
  if [[ "$PLAIN_MODE" == "true" ]]; then
    echo "Legend: ●=unique ◉=shared⟷N ◆=cache apikey=credentials"
  else
    gum_dim "Legend: $(gum style --foreground 120 '●')=unique $(gum style --foreground 212 '◉')=shared⟷N $(gum style --foreground 117 '◆')=cache $(gum style --foreground 220 'apikey')=credentials"
  fi
  echo ""

  # Print each node
  for node in "${NODES_ARRAY[@]}"; do
    local services
    services=$(get_deployments_on_node "$node")
    [[ -z "$services" ]] && continue
    print_node_section_gum "$node" "$services" "${NODE_DISK_INFO[$node]:-}" "$NAMESPACE"
    echo ""
  done

  # Quick commands
  echo ""
  if [[ "$PLAIN_MODE" == "true" ]]; then
    echo "Commands:"
    echo "  kubectl get pods -n $NAMESPACE"
    echo "  kubectl logs -n $NAMESPACE deploy/<name> -f"
    echo "  kubectl exec -n $NAMESPACE -it deploy/<name> -- /bin/sh"
  else
    gum_dim "Commands:"
    echo "  $(gum style --foreground 117 "kubectl get pods -n $NAMESPACE")"
    echo "  $(gum style --foreground 117 "kubectl logs -n $NAMESPACE deploy/<name> -f")"
    echo "  $(gum style --foreground 117 "kubectl exec -n $NAMESPACE -it deploy/<name> -- /bin/sh")"
  fi
  echo ""

  # Status
  if cluster_healthy; then
    gum_success "Cluster is running"
  else
    gum_error "Cluster is not accessible"
  fi
}

# Run
main "$@"
