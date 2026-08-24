#!/bin/bash
# Run model benchmark for browser agent
#
# Usage:
#   ./scripts/run_benchmark.sh                           # Run with defaults
#   ./scripts/run_benchmark.sh --models "qwen2.5:7b"     # Single model
#   ./scripts/run_benchmark.sh --category navigation     # Only navigation tests
#   ./scripts/run_benchmark.sh --no-headless             # Show browser window

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SRC_DIR="$SCRIPT_DIR/../src"

cd "$SRC_DIR"

# Default models to test
DEFAULT_MODELS="ollama/qwen2.5:7b,ollama/qwen2.5:14b,ollama/qwen2.5:32b"

# Check if models flag is provided
if [[ "$*" != *"--models"* ]]; then
  echo "Using default models: $DEFAULT_MODELS"
  echo "Override with: --models 'model1,model2'"
  echo ""
  MODELS_FLAG="--models $DEFAULT_MODELS"
else
  MODELS_FLAG=""
fi

# Run benchmark
python3 -m browser_agent.benchmark "$MODELS_FLAG" "$@"
