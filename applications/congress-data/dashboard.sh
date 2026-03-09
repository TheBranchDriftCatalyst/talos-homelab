#!/usr/bin/env bash
set -euo pipefail

echo "=== Congress Data Code Server ==="
echo ""
echo "Namespace:  congress-gov"
echo "Service:    congress-data:4000 (gRPC)"
echo ""
echo "--- Pods ---"
kubectl get pods -n congress-gov -l app=congress-data 2> /dev/null || echo "(not deployed)"
echo ""
echo "--- Service ---"
kubectl get svc -n congress-gov congress-data 2> /dev/null || echo "(not deployed)"
