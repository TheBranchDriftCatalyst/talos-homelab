#!/bin/bash
# Fargate Example Configuration
# Run ec2-agent monitoring a Fargate cluster

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# ECS cluster to monitor
ECS_CLUSTER="llm-inference-cluster"

# Poll interval for status updates
POLL_INTERVAL="30s"

# Server address
ADDR=":8091"

echo "Starting ec2-agent with Fargate monitoring..."
echo "  ECS Cluster: $ECS_CLUSTER"
echo ""

exec go run "$SCRIPT_DIR/../../cmd/main.go" \
  -addr="$ADDR" \
  -ecs-cluster="$ECS_CLUSTER" \
  -poll="$POLL_INTERVAL"
