#!/bin/sh
set -e

# Configuration from environment
DUCKDNS_DOMAINS="${DUCKDNS_DOMAINS:?DUCKDNS_DOMAINS required (comma-separated pool)}"
DUCKDNS_TOKEN="${DUCKDNS_TOKEN:?DUCKDNS_TOKEN required}"
REFRESH_INTERVAL="${REFRESH_INTERVAL:-60}"
ROTATION_INTERVAL_SECONDS="${ROTATION_INTERVAL_SECONDS:-0}"
STATE_FILE="/shared/ddns-state.json"
PORT_FILE="/tmp/gluetun/forwarded_port"
GLUETUN_HEALTH="http://localhost:9999"
GLUETUN_API="http://localhost:8000"

# Parse domain pool into array-like list
domain_count=0
remaining="$DUCKDNS_DOMAINS"
while [ -n "$remaining" ]; do
  domain="${remaining%%,*}"
  eval "DOMAIN_${domain_count}=\"${domain}\""
  domain_count=$((domain_count + 1))
  if [ "$domain" = "$remaining" ]; then
    remaining=""
  else
    remaining="${remaining#*,}"
  fi
done
current_index=0

get_domain() {
  eval "echo \$DOMAIN_${1}"
}

# Cleanup on exit: clear DuckDNS record
cleanup() {
  echo "[ddns] SIGTERM received, clearing DNS record..."
  domain=$(get_domain "$current_index")
  curl -s "https://www.duckdns.org/update?domains=${domain}&token=${DUCKDNS_TOKEN}&clear=true" || true
  echo "[ddns] Cleanup done"
  exit 0
}
trap cleanup TERM INT

# --- Startup Phase ---

echo "[ddns] Waiting for gluetun to be healthy..."
until curl -sf "$GLUETUN_HEALTH" > /dev/null 2>&1; do
  sleep 5
done
echo "[ddns] Gluetun is healthy"

# Get VPN public IP
get_vpn_ip() {
  curl -sf "${GLUETUN_API}/v1/publicip/ip" | sed 's/.*"public_ip":"\([^"]*\)".*/\1/'
}

# Get forwarded port
get_forwarded_port() {
  if [ -f "$PORT_FILE" ]; then
    cat "$PORT_FILE" 2> /dev/null | tr -d '[:space:]'
  else
    echo ""
  fi
}

current_ip=$(get_vpn_ip)
current_port=$(get_forwarded_port)
current_domain=$(get_domain "$current_index")

echo "[ddns] VPN IP: ${current_ip}"
echo "[ddns] Forwarded port: ${current_port}"
echo "[ddns] Domain: ${current_domain}.duckdns.org"

# Update DuckDNS
update_dns() {
  local domain="$1"
  local ip="$2"
  result=$(curl -s "https://www.duckdns.org/update?domains=${domain}&token=${DUCKDNS_TOKEN}&ip=${ip}")
  if [ "$result" = "OK" ]; then
    echo "[ddns] DuckDNS updated: ${domain}.duckdns.org -> ${ip}"
    return 0
  else
    echo "[ddns] DuckDNS update FAILED for ${domain}: ${result}"
    return 1
  fi
}

# Write state file
write_state() {
  local domain="$1"
  local ip="$2"
  local port="$3"
  local index="$4"
  cat > "$STATE_FILE" << JSONEOF
{
  "domain": "${domain}.duckdns.org",
  "ip": "${ip}",
  "port": "${port}",
  "url": "http://${domain}.duckdns.org:${port}",
  "domain_index": ${index},
  "created_at": "$(date -u +%Y-%m-%dT%H:%M:%SZ)",
  "updated_at": "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
}
JSONEOF
}

# Initial DNS update
update_dns "$current_domain" "$current_ip"
write_state "$current_domain" "$current_ip" "$current_port" "$current_index"

if [ -n "$current_port" ]; then
  echo "[ddns] === Access URL: http://${current_domain}.duckdns.org:${current_port} ==="
else
  echo "[ddns] === Domain: http://${current_domain}.duckdns.org (no forwarded port yet) ==="
fi

# --- Refresh Loop ---

rotation_start=$(date +%s)

while true; do
  sleep "$REFRESH_INTERVAL"

  new_ip=$(get_vpn_ip)
  new_port=$(get_forwarded_port)

  ip_changed=false
  port_changed=false
  rotated=false

  # Check if IP changed
  if [ "$new_ip" != "$current_ip" ] && [ -n "$new_ip" ]; then
    echo "[ddns] IP changed: ${current_ip} -> ${new_ip}"
    current_ip="$new_ip"
    ip_changed=true
  fi

  # Check if port changed
  if [ "$new_port" != "$current_port" ] && [ -n "$new_port" ]; then
    echo "[ddns] Port changed: ${current_port} -> ${new_port}"
    current_port="$new_port"
    port_changed=true
  fi

  # Check if rotation interval elapsed
  if [ "$ROTATION_INTERVAL_SECONDS" -gt 0 ]; then
    now=$(date +%s)
    elapsed=$((now - rotation_start))
    if [ "$elapsed" -ge "$ROTATION_INTERVAL_SECONDS" ]; then
      # Clear old domain
      old_domain=$(get_domain "$current_index")
      curl -s "https://www.duckdns.org/update?domains=${old_domain}&token=${DUCKDNS_TOKEN}&clear=true" > /dev/null || true

      # Cycle to next domain
      current_index=$(((current_index + 1) % domain_count))
      current_domain=$(get_domain "$current_index")
      rotation_start=$now
      rotated=true
      echo "[ddns] Rotated to domain: ${current_domain}.duckdns.org"
    fi
  fi

  # Update DNS if anything changed
  if [ "$ip_changed" = "true" ] || [ "$rotated" = "true" ]; then
    current_domain=$(get_domain "$current_index")
    update_dns "$current_domain" "$current_ip"
  fi

  # Update state if anything changed
  if [ "$ip_changed" = "true" ] || [ "$port_changed" = "true" ] || [ "$rotated" = "true" ]; then
    current_domain=$(get_domain "$current_index")
    write_state "$current_domain" "$current_ip" "$current_port" "$current_index"
    echo "[ddns] === Access URL: http://${current_domain}.duckdns.org:${current_port} ==="
  fi
done
