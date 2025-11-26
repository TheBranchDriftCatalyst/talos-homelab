#!/usr/bin/env bash
# Sync API Keys from *arr services to Kubernetes Secret
#
# This script extracts API keys from running services and updates
# a Kubernetes secret. Run after services have started up.
#
# Usage:
#   ./scripts/sync-api-keys.sh                    # Sync all keys
#   ./scripts/sync-api-keys.sh --dry-run          # Show what would be synced
#   ./scripts/sync-api-keys.sh --service sonarr   # Sync single service

set -euo pipefail

# Configuration
NAMESPACE="${NAMESPACE:-media}"
SECRET_NAME="${SECRET_NAME:-arr-api-keys}"
DRY_RUN=false
SINGLE_SERVICE=""

# Colors
RED='\033[91m'
GREEN='\033[92m'
YELLOW='\033[93m'
CYAN='\033[96m'
DIM='\033[2m'
RESET='\033[0m'

# Parse arguments
while [[ $# -gt 0 ]]; do
  case $1 in
    --dry-run)
      DRY_RUN=true
      shift
      ;;
    --service)
      SINGLE_SERVICE="$2"
      shift 2
      ;;
    --namespace)
      NAMESPACE="$2"
      shift 2
      ;;
    --secret)
      SECRET_NAME="$2"
      shift 2
      ;;
    -h | --help)
      echo "Usage: $0 [OPTIONS]"
      echo ""
      echo "Options:"
      echo "  --dry-run           Show what would be synced without applying"
      echo "  --service NAME      Sync only a specific service"
      echo "  --namespace NS      Target namespace (default: media-prod)"
      echo "  --secret NAME       Secret name (default: arr-api-keys)"
      echo "  -h, --help          Show this help message"
      exit 0
      ;;
    *)
      echo "Unknown option: $1"
      exit 1
      ;;
  esac
done

log() {
  echo -e "${CYAN}[sync-api-keys]${RESET} $1"
}

warn() {
  echo -e "${YELLOW}[sync-api-keys]${RESET} $1"
}

error() {
  echo -e "${RED}[sync-api-keys]${RESET} $1"
}

success() {
  echo -e "${GREEN}[sync-api-keys]${RESET} $1"
}

# Extract API key from *arr service (Sonarr, Radarr, Prowlarr, Readarr, Lidarr)
# These all use /config/config.xml with <ApiKey> tag
get_arr_api_key() {
  local service=$1
  local api_key=""

  if kubectl get deploy "$service" -n "$NAMESPACE" &> /dev/null; then
    api_key=$(kubectl exec -n "$NAMESPACE" "deploy/$service" -- \
      cat /config/config.xml 2> /dev/null |
      sed -n 's/.*<ApiKey>\([^<]*\)<\/ApiKey>.*/\1/p' || true)
  fi

  echo "$api_key"
}

# Extract API key from Overseerr (uses settings.json)
get_overseerr_api_key() {
  local api_key=""

  if kubectl get deploy overseerr -n "$NAMESPACE" &> /dev/null; then
    api_key=$(kubectl exec -n "$NAMESPACE" deploy/overseerr -- \
      cat /config/settings.json 2> /dev/null |
      jq -r '.main.apiKey // empty' 2> /dev/null || true)
  fi

  echo "$api_key"
}

# Extract API key from Plex (uses Preferences.xml)
get_plex_api_key() {
  local api_key=""

  if kubectl get deploy plex -n "$NAMESPACE" &> /dev/null; then
    # Plex token is in Preferences.xml as PlexOnlineToken
    api_key=$(kubectl exec -n "$NAMESPACE" deploy/plex -- \
      cat "/config/Library/Application Support/Plex Media Server/Preferences.xml" 2> /dev/null |
      sed -n 's/.*PlexOnlineToken="\([^"]*\)".*/\1/p' || true)
  fi

  echo "$api_key"
}

# Extract API key from Jellyfin
# Note: Jellyfin API keys are created via the web UI, not auto-generated
# This function checks for any existing API keys in the database
get_jellyfin_api_key() {
  local api_key=""

  # Jellyfin stores API keys in its SQLite database
  # For now, we'll skip auto-extraction as it requires DB access
  # Users should create API keys via Jellyfin UI and add manually

  echo "$api_key"
}

# Extract API key from Tdarr (uses config file)
get_tdarr_api_key() {
  local api_key=""

  if kubectl get deploy tdarr -n "$NAMESPACE" &> /dev/null; then
    # Tdarr stores config in /app/configs/Tdarr_Server_Config.json
    api_key=$(kubectl exec -n "$NAMESPACE" deploy/tdarr -- \
      cat /app/configs/Tdarr_Server_Config.json 2> /dev/null |
      jq -r '.apiKey // empty' 2> /dev/null || true)
  fi

  echo "$api_key"
}

# Main sync function
sync_api_keys() {
  log "Syncing API keys from running services..."
  log "Namespace: $NAMESPACE"
  log "Secret: $SECRET_NAME"
  echo ""

  # Use temp file to store key-value pairs (portable across bash versions)
  local keys_file
  keys_file=$(mktemp)
  trap "rm -f '$keys_file'" RETURN

  # Define services and their extraction methods
  local arr_services="sonarr radarr prowlarr readarr lidarr"

  # Extract *arr API keys
  for service in $arr_services; do
    if [[ -n "$SINGLE_SERVICE" ]] && [[ "$SINGLE_SERVICE" != "$service" ]]; then
      continue
    fi

    log "Checking ${service}..."
    local key
    key=$(get_arr_api_key "$service")

    if [[ -n "$key" ]]; then
      local upper_service
      upper_service=$(echo "$service" | tr '[:lower:]' '[:upper:]')
      echo "${upper_service}_API_KEY=$key" >> "$keys_file"
      success "  ✓ ${service}: ${key:0:8}..."
    else
      warn "  ○ ${service}: not found or not running"
    fi
  done

  # Overseerr
  if [[ -z "$SINGLE_SERVICE" ]] || [[ "$SINGLE_SERVICE" == "overseerr" ]]; then
    log "Checking overseerr..."
    local overseerr_key
    overseerr_key=$(get_overseerr_api_key)
    if [[ -n "$overseerr_key" ]]; then
      echo "OVERSEERR_API_KEY=$overseerr_key" >> "$keys_file"
      success "  ✓ overseerr: ${overseerr_key:0:8}..."
    else
      warn "  ○ overseerr: not found or not running"
    fi
  fi

  # Plex
  if [[ -z "$SINGLE_SERVICE" ]] || [[ "$SINGLE_SERVICE" == "plex" ]]; then
    log "Checking plex..."
    local plex_key
    plex_key=$(get_plex_api_key)
    if [[ -n "$plex_key" ]]; then
      echo "PLEX_TOKEN=$plex_key" >> "$keys_file"
      success "  ✓ plex: ${plex_key:0:8}..."
    else
      warn "  ○ plex: not found or not claimed"
    fi
  fi

  # Tdarr
  if [[ -z "$SINGLE_SERVICE" ]] || [[ "$SINGLE_SERVICE" == "tdarr" ]]; then
    log "Checking tdarr..."
    local tdarr_key
    tdarr_key=$(get_tdarr_api_key)
    if [[ -n "$tdarr_key" ]]; then
      echo "TDARR_API_KEY=$tdarr_key" >> "$keys_file"
      success "  ✓ tdarr: ${tdarr_key:0:8}..."
    else
      warn "  ○ tdarr: not found or no API key configured"
    fi
  fi

  echo ""

  # Check if we have any keys to sync
  local key_count
  key_count=$(wc -l < "$keys_file" | tr -d ' ')
  if [[ "$key_count" -eq 0 ]]; then
    warn "No API keys found to sync"
    return 0
  fi

  # Build the secret
  log "Found $key_count API keys to sync"
  echo ""

  if [[ "$DRY_RUN" == "true" ]]; then
    log "${YELLOW}DRY RUN - would create/update secret:${RESET}"
    echo ""
    echo "apiVersion: v1"
    echo "kind: Secret"
    echo "metadata:"
    echo "  name: $SECRET_NAME"
    echo "  namespace: $NAMESPACE"
    echo "type: Opaque"
    echo "stringData:"
    while IFS='=' read -r key value; do
      echo "  $key: \"$value\""
    done < "$keys_file"
    return 0
  fi

  # Create or update the secret
  log "Creating/updating secret $SECRET_NAME..."

  # Build kubectl create secret command
  local secret_args=""
  while IFS='=' read -r key value; do
    secret_args="$secret_args --from-literal=$key=$value"
  done < "$keys_file"

  # Delete existing secret if it exists, then create new one
  kubectl delete secret "$SECRET_NAME" -n "$NAMESPACE" --ignore-not-found &> /dev/null
  eval "kubectl create secret generic '$SECRET_NAME' -n '$NAMESPACE' $secret_args"

  success "✓ Secret $SECRET_NAME updated with $key_count keys"
  echo ""

  # Also update homepage-secrets if it exists (for dashboard integration)
  if kubectl get secret homepage-secrets -n "$NAMESPACE" &> /dev/null; then
    log "Updating homepage-secrets for dashboard integration..."

    # Build patch with HOMEPAGE_VAR_ prefixed keys
    # Re-read the keys file from the beginning
    local patch_entries=""
    local first=true
    while IFS='=' read -r key value; do
      local homepage_key
      # Convert SONARR_API_KEY to HOMEPAGE_VAR_SONARR_KEY format
      homepage_key=$(echo "$key" | sed 's/_API_KEY/_KEY/' | sed 's/_TOKEN/_KEY/' | sed 's/^/HOMEPAGE_VAR_/')
      local encoded_value
      encoded_value=$(echo -n "$value" | base64)

      if [[ "$first" == "true" ]]; then
        first=false
      else
        patch_entries="$patch_entries,"
      fi
      patch_entries="$patch_entries\"$homepage_key\":\"$encoded_value\""
    done < <(cat "$keys_file")

    local patch_data="{\"data\":{$patch_entries}}"
    kubectl patch secret homepage-secrets -n "$NAMESPACE" -p "$patch_data" --type=merge
    success "✓ homepage-secrets updated"
  fi
}

# Run main function
sync_api_keys
