#!/bin/bash
# EC2 Example Configuration
# Run ec2-agent with llm-worker.sh

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../../../.." && pwd)"

# Path to the actual LLM worker script
WORKER_SCRIPT="$REPO_ROOT/scripts/hybrid-llm/llm-worker.sh"

# EC2 tags to monitor (filter instances by these tags)
EC2_TAGS='{"Name":"llm-worker","Project":"catalyst-llm"}'

# Poll interval for status updates
POLL_INTERVAL="30s"

# Server address
ADDR=":8090"

echo "Starting ec2-agent with EC2 worker..."
echo "  Worker script: $WORKER_SCRIPT"
echo "  EC2 tags: $EC2_TAGS"
echo ""

exec go run "$SCRIPT_DIR/../../cmd/main.go" \
  -addr="$ADDR" \
  -script="$WORKER_SCRIPT" \
  -ec2-tags="$EC2_TAGS" \
  -poll="$POLL_INTERVAL"
