#!/bin/bash
# GPU vs CPU Encoding Performance Comparison
# Runs ffmpeg encoding tests on GPU node vs non-GPU node
# shellcheck disable=SC2001

set -euo pipefail

NAMESPACE="${NAMESPACE:-intel-device-plugins}"
TIMEOUT="${TIMEOUT:-300}"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

log() { echo -e "${BLUE}[INFO]${NC} $*"; }
success() { echo -e "${GREEN}[OK]${NC} $*"; }
warn() { echo -e "${YELLOW}[WARN]${NC} $*"; }
error() { echo -e "${RED}[ERROR]${NC} $*"; }

# Common test script embedded in jobs
TEST_SCRIPT='
echo "=== Node: $(hostname) ==="
echo "=== Creating 10-second 1080p Test Video ==="
time ffmpeg -hide_banner -f lavfi -i testsrc=duration=10:size=1920x1080:rate=30 -c:v rawvideo -pix_fmt yuv420p /tmp/test_input.yuv 2>&1

echo ""
echo "=== H.264 Encoding Test ==="
START=$(date +%s)
ENCODE_CMD
END=$(date +%s)
ELAPSED=$((END - START))
echo "Encoding time: ${ELAPSED}s"
ls -lh /tmp/test_output.mp4 2>/dev/null || echo "Output file not created"

echo ""
echo "=== Test Complete ==="
'

# GPU encoding command
GPU_ENCODE='ffmpeg -hide_banner -vaapi_device /dev/dri/renderD128 \
  -f rawvideo -pix_fmt yuv420p -s 1920x1080 -r 30 -i /tmp/test_input.yuv \
  -vf "format=nv12,hwupload" -c:v h264_vaapi -y /tmp/test_output.mp4 2>&1'

# CPU encoding command (libx264 software encoder)
CPU_ENCODE='ffmpeg -hide_banner \
  -f rawvideo -pix_fmt yuv420p -s 1920x1080 -r 30 -i /tmp/test_input.yuv \
  -c:v libx264 -preset medium -y /tmp/test_output.mp4 2>&1'

create_gpu_job() {
  local script="${TEST_SCRIPT//ENCODE_CMD/$GPU_ENCODE}"
  cat << EOF
apiVersion: batch/v1
kind: Job
metadata:
  name: gpu-encode-benchmark
  namespace: $NAMESPACE
spec:
  ttlSecondsAfterFinished: 60
  template:
    spec:
      restartPolicy: Never
      containers:
        - name: ffmpeg
          image: linuxserver/ffmpeg:latest
          command: ["/bin/bash", "-c"]
          args:
            - |
$(echo "$script" | sed 's/^/              /')
          resources:
            limits:
              gpu.intel.com/i915: "1"
          securityContext:
            capabilities:
              add: ["SYS_ADMIN"]
          volumeMounts:
            - name: dri
              mountPath: /dev/dri
      volumes:
        - name: dri
          hostPath:
            path: /dev/dri
            type: Directory
      affinity:
        nodeAffinity:
          requiredDuringSchedulingIgnoredDuringExecution:
            nodeSelectorTerms:
              - matchExpressions:
                  - key: intel.feature.node.kubernetes.io/gpu
                    operator: In
                    values: ["true"]
EOF
}

create_cpu_job() {
  local script="${TEST_SCRIPT//ENCODE_CMD/$CPU_ENCODE}"
  cat << EOF
apiVersion: batch/v1
kind: Job
metadata:
  name: cpu-encode-benchmark
  namespace: $NAMESPACE
spec:
  ttlSecondsAfterFinished: 60
  template:
    spec:
      restartPolicy: Never
      containers:
        - name: ffmpeg
          image: linuxserver/ffmpeg:latest
          command: ["/bin/bash", "-c"]
          args:
            - |
$(echo "$script" | sed 's/^/              /')
          resources:
            requests:
              cpu: "2"
              memory: "2Gi"
            limits:
              cpu: "4"
              memory: "4Gi"
      affinity:
        nodeAffinity:
          requiredDuringSchedulingIgnoredDuringExecution:
            nodeSelectorTerms:
              - matchExpressions:
                  - key: intel.feature.node.kubernetes.io/gpu
                    operator: NotIn
                    values: ["true"]
EOF
}

cleanup() {
  log "Cleaning up old jobs..."
  kubectl delete job gpu-encode-benchmark cpu-encode-benchmark -n "$NAMESPACE" --ignore-not-found 2> /dev/null || true
}

run_job() {
  local job_name=$1
  local create_fn=$2

  log "Creating $job_name job..."
  $create_fn | kubectl apply -f - || {
    error "Failed to create $job_name job"
    return 1
  }

  log "Waiting for $job_name to complete (timeout: ${TIMEOUT}s)..."
  if kubectl wait --for=condition=complete "job/$job_name" -n "$NAMESPACE" --timeout="${TIMEOUT}s" 2> /dev/null; then
    success "$job_name completed"
    return 0
  else
    # Check if job failed
    local status=$(kubectl get job "$job_name" -n "$NAMESPACE" -o jsonpath='{.status.failed}' 2> /dev/null)
    if [[ "$status" == "1" ]]; then
      error "$job_name failed"
    else
      error "$job_name timed out"
    fi
    return 1
  fi
}

get_logs() {
  local job_name=$1
  kubectl logs "job/$job_name" -n "$NAMESPACE" 2> /dev/null
}

main() {
  echo ""
  echo "=============================================="
  echo "  GPU vs CPU Encoding Performance Comparison"
  echo "=============================================="
  echo ""

  # Check for GPU nodes
  local gpu_nodes=$(kubectl get nodes -l intel.feature.node.kubernetes.io/gpu=true -o name 2> /dev/null | wc -l)
  local non_gpu_nodes=$(kubectl get nodes -l 'intel.feature.node.kubernetes.io/gpu!=true' -o name 2> /dev/null | wc -l)

  log "GPU nodes: $gpu_nodes, Non-GPU nodes: $non_gpu_nodes"

  if [[ "$gpu_nodes" -eq 0 ]]; then
    error "No GPU nodes found with label intel.feature.node.kubernetes.io/gpu=true"
    exit 1
  fi

  if [[ "$non_gpu_nodes" -eq 0 ]]; then
    warn "No non-GPU nodes found - CPU test may schedule on GPU node"
  fi

  cleanup

  echo ""
  echo "=============================================="
  echo "  Running GPU Encoding Test (VAAPI H.264)"
  echo "=============================================="

  if run_job "gpu-encode-benchmark" "create_gpu_job"; then
    echo ""
    echo "--- GPU Test Results ---"
    get_logs "gpu-encode-benchmark"
  fi

  echo ""
  echo "=============================================="
  echo "  Running CPU Encoding Test (libx264)"
  echo "=============================================="

  if run_job "cpu-encode-benchmark" "create_cpu_job"; then
    echo ""
    echo "--- CPU Test Results ---"
    get_logs "cpu-encode-benchmark"
  fi

  echo ""
  echo "=============================================="
  echo "  Comparison Complete"
  echo "=============================================="
  echo ""
  log "Check the 'Encoding time' values above to compare GPU vs CPU performance"

  cleanup
}

main "$@"
