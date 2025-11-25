#!/bin/bash
# Script to create the arr-stack-credentials item in 1Password
# Requires: 1Password CLI (op) installed and authenticated

set -e

VAULT="catalyst-eso"
ITEM_NAME="arr-stack-credentials"

echo "Creating 1Password item for arr-stack credentials..."
echo "Vault: $VAULT"
echo "Item: $ITEM_NAME"
echo ""

# Check if op CLI is installed
if ! command -v op &> /dev/null; then
    echo "Error: 1Password CLI (op) is not installed"
    echo "Install from: https://developer.1password.com/docs/cli/get-started/"
    exit 1
fi

# Check if logged in
if ! op account list &> /dev/null; then
    echo "Error: Not logged in to 1Password CLI"
    echo "Run: eval \$(op signin)"
    exit 1
fi

# Check if vault exists
if ! op vault get "$VAULT" &> /dev/null; then
    echo "Error: Vault '$VAULT' not found"
    echo "Available vaults:"
    op vault list
    exit 1
fi

# Check if item already exists
if op item get "$ITEM_NAME" --vault "$VAULT" &> /dev/null; then
    echo "Warning: Item '$ITEM_NAME' already exists in vault '$VAULT'"
    read -p "Do you want to update it? (y/N): " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        echo "Aborted."
        exit 0
    fi
    UPDATE=true
else
    UPDATE=false
fi

echo ""
echo "Please provide the following credentials:"
echo "(Leave blank to skip, you can add them later)"
echo ""

# Function to read secret
read_secret() {
    local prompt="$1"
    local var_name="$2"
    read -sp "$prompt: " value
    echo
    eval "$var_name='$value'"
}

# Function to read text
read_text() {
    local prompt="$1"
    local var_name="$2"
    local default="$3"
    read -p "$prompt [$default]: " value
    value="${value:-$default}"
    eval "$var_name='$value'"
}

# Collect values
echo "=== Media Management ==="
read_secret "Sonarr API Key" SONARR_KEY
read_secret "Radarr API Key" RADARR_KEY
read_secret "Readarr API Key" READARR_KEY
read_secret "Prowlarr API Key" PROWLARR_KEY

echo ""
echo "=== Media Servers ==="
read_secret "Plex Token" PLEX_TOKEN
read_secret "Jellyfin API Key" JELLYFIN_KEY
read_secret "Overseerr API Key" OVERSEERR_KEY

echo ""
echo "=== Infrastructure ==="
read_secret "ArgoCD Token" ARGOCD_TOKEN
read_text "Grafana Username" GRAFANA_USER "admin"
read_secret "Grafana Password" GRAFANA_PASS

echo ""
echo "Creating/updating 1Password item..."

# Build the command
if [ "$UPDATE" = true ]; then
    # Update existing item
    CMD="op item edit '$ITEM_NAME' --vault '$VAULT'"
else
    # Create new item
    CMD="op item create --category='Secure Note' --title='$ITEM_NAME' --vault='$VAULT'"
fi

# Add fields
[ -n "$SONARR_KEY" ] && CMD="$CMD sonarr_api_key[password]='$SONARR_KEY'"
[ -n "$RADARR_KEY" ] && CMD="$CMD radarr_api_key[password]='$RADARR_KEY'"
[ -n "$READARR_KEY" ] && CMD="$CMD readarr_api_key[password]='$READARR_KEY'"
[ -n "$PROWLARR_KEY" ] && CMD="$CMD prowlarr_api_key[password]='$PROWLARR_KEY'"
[ -n "$PLEX_TOKEN" ] && CMD="$CMD plex_token[password]='$PLEX_TOKEN'"
[ -n "$JELLYFIN_KEY" ] && CMD="$CMD jellyfin_api_key[password]='$JELLYFIN_KEY'"
[ -n "$OVERSEERR_KEY" ] && CMD="$CMD overseerr_api_key[password]='$OVERSEERR_KEY'"
[ -n "$ARGOCD_TOKEN" ] && CMD="$CMD argocd_token[password]='$ARGOCD_TOKEN'"
[ -n "$GRAFANA_USER" ] && CMD="$CMD grafana_username[text]='$GRAFANA_USER'"
[ -n "$GRAFANA_PASS" ] && CMD="$CMD grafana_password[password]='$GRAFANA_PASS'"

# Execute the command
eval "$CMD"

echo ""
echo "✅ Success! 1Password item created/updated."
echo ""
echo "Next steps:"
echo "1. Verify the ExternalSecret is syncing:"
echo "   kubectl get externalsecret homepage-secrets -n media-dev"
echo ""
echo "2. Check the created secret:"
echo "   kubectl get secret homepage-secrets -n media-dev"
echo ""
echo "3. Deploy homepage:"
echo "   kubectl apply -k applications/arr-stack/base/homepage/"
echo ""
echo "4. Access the dashboard:"
echo "   http://homepage.talos00"
