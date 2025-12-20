#!/bin/bash
# Arr-Stack Migration Script
# Migrates Sonarr/Radarr/Prowlarr data from .drogon-app to K8s
#
# Usage:
#   ./scripts/migrate-arr-stack.sh [--app=sonarr|radarr|prowlarr|all] [--dry-run] [--skip-restore]
#
# Prerequisites:
#   - kubectl configured for cluster access
#   - .drogon-app/services/arrs/ contains sonarr/radarr data
#   - .drogon-app/services/prowlarr/ contains prowlarr data
#   - 1Password ExternalSecret deployed (arr-stack-secrets)

set -euo pipefail

# Configuration
NAMESPACE="${NAMESPACE:-media}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
DROGON_BASE="$REPO_ROOT/.drogon-app/services"
MIGRATION_DIR="$REPO_ROOT/applications/arr-stack/base/migration"

# Defaults
APP="all"
DRY_RUN=false
SKIP_RESTORE=false
TIMEOUT=120

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

log() { echo -e "${BLUE}[INFO]${NC} $*"; }
success() { echo -e "${GREEN}[OK]${NC} $*"; }
warn() { echo -e "${YELLOW}[WARN]${NC} $*"; }
error() { echo -e "${RED}[ERROR]${NC} $*" >&2; }
die() { error "$*"; exit 1; }

# Parse arguments
for arg in "$@"; do
  case $arg in
    --app=*)
      APP="${arg#*=}"
      ;;
    --dry-run)
      DRY_RUN=true
      ;;
    --skip-restore)
      SKIP_RESTORE=true
      ;;
    --help|-h)
      echo "Usage: $0 [--app=sonarr|radarr|prowlarr|all] [--dry-run] [--skip-restore]"
      echo ""
      echo "Options:"
      echo "  --app=APP       Migrate specific app (default: all)"
      echo "  --dry-run       Show what would be done without making changes"
      echo "  --skip-restore  Copy files but don't trigger app restore"
      exit 0
      ;;
    *)
      warn "Unknown argument: $arg"
      ;;
  esac
done

# Validate APP
case "$APP" in
  sonarr|radarr|prowlarr|sabnzbd|all) ;;
  *) die "Invalid app: $APP. Must be sonarr, radarr, prowlarr, sabnzbd, or all" ;;
esac

log "=== Arr-Stack Migration ==="
log "App: $APP"
log "Dry run: $DRY_RUN"
log "Skip restore: $SKIP_RESTORE"
echo ""

# Pre-flight checks
preflight_checks() {
  log "Running pre-flight checks..."

  # Check kubectl
  if ! command -v kubectl &> /dev/null; then
    die "kubectl not found"
  fi

  # Check cluster access
  if ! kubectl cluster-info &> /dev/null; then
    die "Cannot connect to Kubernetes cluster"
  fi
  success "Cluster connection OK"

  # Check source directories
  local apps_to_check=()
  case "$APP" in
    all) apps_to_check=(sonarr radarr prowlarr sabnzbd) ;;
    *) apps_to_check=("$APP") ;;
  esac

  for app in "${apps_to_check[@]}"; do
    local source_path
    case "$app" in
      prowlarr|sabnzbd) source_path="$DROGON_BASE/$app" ;;
      *) source_path="$DROGON_BASE/arrs/$app" ;;
    esac

    if [ ! -d "$source_path" ]; then
      die "Source not found: $source_path"
    fi
    success "Source exists: $source_path"

    # Check for critical files (sabnzbd uses .ini, others use config.xml)
    if [ "$app" = "sabnzbd" ]; then
      if [ ! -f "$source_path/sabnzbd.ini" ]; then
        warn "sabnzbd.ini missing in $source_path"
      fi
    else
      if [ ! -f "$source_path/config.xml" ]; then
        warn "config.xml missing in $source_path"
      fi
      if [ ! -d "$source_path/asp" ]; then
        warn "asp/ directory missing in $source_path (encrypted credentials won't work)"
      fi
    fi
  done

  # Check target PVCs exist
  for app in "${apps_to_check[@]}"; do
    if ! kubectl get pvc "${app}-config" -n "$NAMESPACE" &> /dev/null; then
      die "Target PVC not found: ${app}-config in namespace $NAMESPACE"
    fi
    success "Target PVC exists: ${app}-config"
  done

  success "Pre-flight checks passed"
  echo ""
}

# Scale down app deployment
scale_down() {
  local app="$1"
  log "Scaling down $app..."

  if $DRY_RUN; then
    log "[DRY RUN] Would scale down deployment/$app"
    return
  fi

  kubectl scale deployment/"$app" -n "$NAMESPACE" --replicas=0 2>/dev/null || \
    warn "Deployment $app not found or already scaled down"

  # Wait for pods to terminate
  log "Waiting for $app pods to terminate..."
  kubectl wait --for=delete pod -l app="$app" -n "$NAMESPACE" --timeout=60s 2>/dev/null || true
  success "$app scaled down"
}

# Scale up app deployment
scale_up() {
  local app="$1"
  log "Scaling up $app..."

  if $DRY_RUN; then
    log "[DRY RUN] Would scale up deployment/$app"
    return
  fi

  kubectl scale deployment/"$app" -n "$NAMESPACE" --replicas=1 2>/dev/null || \
    warn "Deployment $app not found"

  # Wait for pod to be ready
  log "Waiting for $app pod to be ready..."
  kubectl wait --for=condition=ready pod -l app="$app" -n "$NAMESPACE" --timeout="${TIMEOUT}s" || \
    warn "Timeout waiting for $app pod"
  success "$app scaled up"
}

# Copy files to PVC using a temporary pod
copy_to_pvc() {
  local app="$1"
  local source_path="$2"

  log "Copying files for $app..."

  if $DRY_RUN; then
    log "[DRY RUN] Would copy $source_path to ${app}-config PVC"
    return
  fi

  # Create a temporary pod for copying
  local pod_name="arr-migration-copy-${app}"

  kubectl run "$pod_name" \
    --image=busybox:1.36 \
    --namespace="$NAMESPACE" \
    --restart=Never \
    --overrides='{
      "spec": {
        "tolerations": [{"key": "node-role.kubernetes.io/control-plane", "operator": "Exists", "effect": "NoSchedule"}],
        "containers": [{
          "name": "copy",
          "image": "busybox:1.36",
          "command": ["sleep", "3600"],
          "volumeMounts": [{"name": "config", "mountPath": "/config"}]
        }],
        "volumes": [{"name": "config", "persistentVolumeClaim": {"claimName": "'"${app}"'-config"}}]
      }
    }' \
    -- sleep 3600

  # Wait for pod to be ready
  kubectl wait --for=condition=ready pod "$pod_name" -n "$NAMESPACE" --timeout=60s

  # Create directories
  kubectl exec "$pod_name" -n "$NAMESPACE" -- mkdir -p /config/asp /config/Backups/scheduled /config/admin

  # SABnzbd has different config structure
  if [ "$app" = "sabnzbd" ]; then
    # Copy sabnzbd.ini
    if [ -f "$source_path/sabnzbd.ini" ]; then
      log "  Copying sabnzbd.ini"
      kubectl cp "$source_path/sabnzbd.ini" "$NAMESPACE/$pod_name:/config/sabnzbd.ini"
    fi
    # Copy admin directory
    if [ -d "$source_path/admin" ]; then
      log "  Copying admin directory"
      for admin_file in "$source_path/admin/"*; do
        if [ -f "$admin_file" ]; then
          kubectl cp "$admin_file" "$NAMESPACE/$pod_name:/config/admin/$(basename "$admin_file")"
        fi
      done
    fi
  else
    # *arr apps use config.xml and asp/
    # Copy config.xml
    if [ -f "$source_path/config.xml" ]; then
      log "  Copying config.xml"
      kubectl cp "$source_path/config.xml" "$NAMESPACE/$pod_name:/config/config.xml"
    fi

    # Copy asp/ encryption keys
    if [ -d "$source_path/asp" ]; then
      log "  Copying encryption keys (asp/)"
      for key_file in "$source_path/asp/"*.xml; do
        if [ -f "$key_file" ]; then
          kubectl cp "$key_file" "$NAMESPACE/$pod_name:/config/asp/$(basename "$key_file")"
        fi
      done
    fi

    # Copy latest backup
    if [ -d "$source_path/Backups/scheduled" ]; then
      local latest_backup
      latest_backup=$(ls -t "$source_path/Backups/scheduled/"*.zip 2>/dev/null | head -1)
      if [ -n "$latest_backup" ]; then
        log "  Copying backup: $(basename "$latest_backup")"
        kubectl cp "$latest_backup" "$NAMESPACE/$pod_name:/config/Backups/scheduled/$(basename "$latest_backup")"
      fi
    fi
  fi

  # Cleanup pod
  kubectl delete pod "$pod_name" -n "$NAMESPACE" --wait=false

  success "Files copied for $app"
}

# Trigger restore via API
trigger_restore() {
  local app="$1"

  if $SKIP_RESTORE; then
    log "Skipping restore for $app (--skip-restore)"
    return
  fi

  # SABnzbd doesn't have backup/restore - config is copied directly
  if [ "$app" = "sabnzbd" ]; then
    log "SABnzbd config copied directly (no restore step needed)"
    log "Verify at: http://${app}.talos00"
    echo ""
    return
  fi

  log "To trigger restore for $app:"
  log "  1. Open http://${app}.talos00 in browser"
  log "  2. Go to System > Backup"
  log "  3. Select the backup file and click Restore"
  log ""
  log "Or use API (requires API key from 1Password):"
  log "  curl -X POST 'http://${app}.talos00/api/v1/system/backup/restore/upload' \\"
  log "    -H 'X-Api-Key: YOUR_API_KEY' \\"
  log "    -F 'file=@backup.zip'"
  echo ""
}

# Migrate a single app
migrate_app() {
  local app="$1"
  local source_path

  case "$app" in
    prowlarr|sabnzbd) source_path="$DROGON_BASE/$app" ;;
    *) source_path="$DROGON_BASE/arrs/$app" ;;
  esac

  log "=== Migrating $app ==="

  scale_down "$app"
  copy_to_pvc "$app" "$source_path"
  scale_up "$app"
  trigger_restore "$app"

  success "=== $app migration complete ==="
  echo ""
}

# Main
main() {
  preflight_checks

  if $DRY_RUN; then
    warn "DRY RUN MODE - no changes will be made"
    echo ""
  fi

  case "$APP" in
    all)
      migrate_app "sonarr"
      migrate_app "radarr"
      migrate_app "prowlarr"
      migrate_app "sabnzbd"
      ;;
    *)
      migrate_app "$APP"
      ;;
  esac

  success "=== Migration Complete ==="
  log ""
  log "Next steps:"
  log "  1. Check app logs: kubectl logs -f deploy/<app> -n $NAMESPACE"
  log "  2. Trigger restore in each app's UI (System > Backup > Restore)"
  log "  3. Update library root folder paths to match K8s mounts"
  log "  4. Test indexer and download client connectivity"
}

main
