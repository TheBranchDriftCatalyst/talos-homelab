#!/bin/bash
# Technitium DNS Server Configuration Script
# Automatically configures Technitium via API

set -e

TECHNITIUM_URL="${TECHNITIUM_URL:-http://dns.talos00:5380}"
TECHNITIUM_USER="${TECHNITIUM_USER:-admin}"
TECHNITIUM_PASSWORD="${TECHNITIUM_PASSWORD:-admin}"
DNS_ZONE="${DNS_ZONE:-talos00}"

echo "🔧 Configuring Technitium DNS Server"
echo "===================================="
echo "  URL: $TECHNITIUM_URL"
echo "  Zone: $DNS_ZONE"
echo ""

# Wait for Technitium to be accessible
echo "⏳ Waiting for Technitium API to be available..."
for i in {1..30}; do
    if curl -s -f "$TECHNITIUM_URL/api/ping" > /dev/null 2>&1; then
        echo "✅ Technitium API is accessible"
        break
    fi
    if [ $i -eq 30 ]; then
        echo "❌ Technitium API not accessible after 30 attempts"
        echo "   Please check if Technitium is running and accessible"
        exit 1
    fi
    echo "   Attempt $i/30... waiting 2s"
    sleep 2
done

# Login and get token
echo ""
echo "🔐 Authenticating..."
LOGIN_RESPONSE=$(curl -s -X POST "$TECHNITIUM_URL/api/user/login" \
    -d "user=$TECHNITIUM_USER" \
    -d "pass=$TECHNITIUM_PASSWORD")

TOKEN=$(echo "$LOGIN_RESPONSE" | grep -o '"token":"[^"]*"' | cut -d'"' -f4)

if [ -z "$TOKEN" ]; then
    echo "❌ Failed to authenticate with Technitium"
    echo "   Response: $LOGIN_RESPONSE"
    exit 1
fi

echo "✅ Authenticated successfully"

# Check if zone exists
echo ""
echo "🔍 Checking if zone '$DNS_ZONE' exists..."
ZONES_RESPONSE=$(curl -s -X POST "$TECHNITIUM_URL/api/zones/list" \
    -d "token=$TOKEN")

if echo "$ZONES_RESPONSE" | grep -q "\"name\":\"$DNS_ZONE\""; then
    echo "✅ Zone '$DNS_ZONE' already exists"
else
    echo "📝 Creating zone '$DNS_ZONE'..."
    CREATE_ZONE_RESPONSE=$(curl -s -X POST "$TECHNITIUM_URL/api/zones/create" \
        -d "token=$TOKEN" \
        -d "zone=$DNS_ZONE" \
        -d "type=Primary")

    if echo "$CREATE_ZONE_RESPONSE" | grep -q '"status":"ok"'; then
        echo "✅ Zone '$DNS_ZONE' created successfully"
    else
        echo "❌ Failed to create zone"
        echo "   Response: $CREATE_ZONE_RESPONSE"
        exit 1
    fi
fi

# Optional: Add initial DNS records
echo ""
echo "📝 Adding initial DNS records..."

# Add DNS server itself
curl -s -X POST "$TECHNITIUM_URL/api/zones/records/add" \
    -d "token=$TOKEN" \
    -d "zone=$DNS_ZONE" \
    -d "name=dns" \
    -d "type=A" \
    -d "value=${TALOS_NODE:-192.168.1.54}" \
    -d "ttl=300" > /dev/null

echo "✅ Added: dns.$DNS_ZONE"

echo ""
echo "✅ Technitium configuration complete!"
echo ""
echo "🌐 Zone Information:"
echo "   Zone: $DNS_ZONE"
echo "   Type: Primary (Authoritative)"
echo "   Records: Managed by catalyst-dns-sync"
echo ""
echo "🔗 Web UI: $TECHNITIUM_URL"
echo "   Username: $TECHNITIUM_USER"
echo "   Password: $TECHNITIUM_PASSWORD"
echo ""
