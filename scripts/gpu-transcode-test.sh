#!/usr/bin/env bash
#
# GPU Transcode Test Script
# Creates Kubernetes Jobs to test GPU encoding capabilities on each node
#
# Usage:
#   ./scripts/gpu-transcode-test.sh                    # Test all GPU nodes
#   ./scripts/gpu-transcode-test.sh --node talos02-gpu # Test specific node
#   ./scripts/gpu-transcode-test.sh --quick            # Quick test (fewer codecs)
#

set -euo pipefail

NAMESPACE="scratch"
JOB_PREFIX="gpu-test"
IMAGE="linuxserver/ffmpeg:latest"
TEST_DURATION=3
CLEANUP=${CLEANUP:-true}

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m'

# Get all schedulable nodes in the cluster
get_all_nodes() {
    kubectl get nodes -o jsonpath='{.items[*].metadata.name}' | tr ' ' '\n'
}

log() { echo -e "$1"; }
header() {
    log ""
    log "${BLUE}═══════════════════════════════════════════════════════════════${NC}"
    log "${BLUE}  $1${NC}"
    log "${BLUE}═══════════════════════════════════════════════════════════════${NC}"
}
subheader() { log "\n${YELLOW}--- $1 ---${NC}"; }

# Detect GPU type for a node by checking labels and device files
detect_node_gpu_type() {
    local node="$1"

    # Check for node labels first (if labeled)
    local labels=$(kubectl get node "$node" -o jsonpath='{.metadata.labels}' 2>/dev/null)

    if echo "$labels" | grep -qi "nvidia"; then
        echo "nvidia"
        return
    fi

    if echo "$labels" | grep -qi "intel"; then
        echo "intel"
        return
    fi

    if echo "$labels" | grep -qi "amd"; then
        echo "amd"
        return
    fi

    # Fallback: known node mapping for this cluster
    case "$node" in
        *gpu*|talos02*) echo "intel" ;;   # Intel Arc nodes
        talos03)        echo "amd" ;;     # AMD VAAPI
        talos05)        echo "nvidia" ;;  # NVIDIA P2000
        talos04)        echo "nvidia" ;;  # NVIDIA GPU
        *)              echo "cpu" ;;     # CPU-only fallback
    esac
}

# Generate Job YAML for a specific node
generate_job_yaml() {
    local node="$1"
    local gpu_type="$2"
    local job_name="${JOB_PREFIX}-${node}"

    local gpu_volumes=""
    local gpu_volume_mounts=""
    local security_context=""
    local runtime_class=""

    case "$gpu_type" in
        intel|amd)
            gpu_volumes='
        - name: dri
          hostPath:
            path: /dev/dri
            type: Directory'
            gpu_volume_mounts='
            - name: dri
              mountPath: /dev/dri'
            security_context='
          securityContext:
            privileged: true'
            ;;
        nvidia)
            # NVIDIA uses device plugin, but we need privileged for now due to CDI issues
            gpu_volumes='
        - name: nvidia
          hostPath:
            path: /dev/nvidia0
            type: CharDevice
        - name: nvidiactl
          hostPath:
            path: /dev/nvidiactl
            type: CharDevice
        - name: nvidia-uvm
          hostPath:
            path: /dev/nvidia-uvm
            type: CharDevice'
            gpu_volume_mounts='
            - name: nvidia
              mountPath: /dev/nvidia0
            - name: nvidiactl
              mountPath: /dev/nvidiactl
            - name: nvidia-uvm
              mountPath: /dev/nvidia-uvm'
            security_context='
          securityContext:
            privileged: true'
            ;;
        cpu|*)
            # CPU-only nodes - no special volumes needed
            gpu_volumes=""
            gpu_volume_mounts=""
            security_context=""
            ;;
    esac

    # Build volume mounts section
    local volume_mounts_section="
            - name: tmp
              mountPath: /tmp"
    if [[ -n "$gpu_volume_mounts" ]]; then
        volume_mounts_section="${gpu_volume_mounts}${volume_mounts_section}"
    fi

    # Build volumes section
    local volumes_section="
        - name: tmp
          emptyDir: {}"
    if [[ -n "$gpu_volumes" ]]; then
        volumes_section="${gpu_volumes}${volumes_section}"
    fi

    cat <<EOF
apiVersion: batch/v1
kind: Job
metadata:
  name: ${job_name}
  namespace: ${NAMESPACE}
  labels:
    app: gpu-transcode-test
    node: ${node}
spec:
  ttlSecondsAfterFinished: 300
  backoffLimit: 0
  template:
    metadata:
      labels:
        app: gpu-transcode-test
    spec:
      restartPolicy: Never
      nodeSelector:
        kubernetes.io/hostname: ${node}
      containers:
        - name: ffmpeg
          image: ${IMAGE}
          command: ["sleep", "infinity"]${security_context}
          volumeMounts:${volume_mounts_section}
      volumes:${volumes_section}
EOF
}

# Create and wait for job pod to be ready
create_test_job() {
    local node="$1"
    local gpu_type="$2"
    local job_name="${JOB_PREFIX}-${node}"

    log "${CYAN}Creating test job for ${node} (${gpu_type})...${NC}"

    # Delete existing job if any
    kubectl delete job "$job_name" -n "$NAMESPACE" --ignore-not-found &>/dev/null

    # Create job
    generate_job_yaml "$node" "$gpu_type" | kubectl apply -f - &>/dev/null

    # Wait for pod to be running
    local timeout=60
    local elapsed=0
    while [[ $elapsed -lt $timeout ]]; do
        local phase=$(kubectl get pods -n "$NAMESPACE" -l "job-name=$job_name" -o jsonpath='{.items[0].status.phase}' 2>/dev/null || echo "Pending")
        if [[ "$phase" == "Running" ]]; then
            log "${GREEN}Job pod running${NC}"
            return 0
        fi
        sleep 2
        elapsed=$((elapsed + 2))
    done

    log "${RED}Timeout waiting for job pod${NC}"
    return 1
}

# Get pod name for a job
get_job_pod() {
    local job_name="$1"
    kubectl get pods -n "$NAMESPACE" -l "job-name=$job_name" -o jsonpath='{.items[0].metadata.name}' 2>/dev/null
}

# Run encode test in job pod
run_encode_test() {
    local pod="$1"
    local encoder="$2"
    local gpu_type="$3"

    local cmd=""

    case "$encoder" in
        *_qsv)
            cmd="ffmpeg -hide_banner -y -init_hw_device qsv=hw -filter_hw_device hw -f lavfi -i testsrc=duration=${TEST_DURATION}:size=1920x1080:rate=30 -vf 'format=nv12,hwupload=extra_hw_frames=64' -c:v $encoder -preset fast -f null - 2>&1"
            ;;
        *_vaapi)
            cmd="ffmpeg -hide_banner -y -vaapi_device /dev/dri/renderD128 -f lavfi -i testsrc=duration=${TEST_DURATION}:size=1920x1080:rate=30 -vf 'format=nv12,hwupload' -c:v $encoder -f null - 2>&1"
            ;;
        *_nvenc)
            cmd="ffmpeg -hide_banner -y -f lavfi -i testsrc=duration=${TEST_DURATION}:size=1920x1080:rate=30 -c:v $encoder -preset fast -f null - 2>&1"
            ;;
        lib*)
            cmd="ffmpeg -hide_banner -y -f lavfi -i testsrc=duration=${TEST_DURATION}:size=1920x1080:rate=30 -c:v $encoder -preset fast -f null - 2>&1"
            ;;
    esac

    local result=$(kubectl exec -n "$NAMESPACE" "$pod" -- bash -c "$cmd" 2>&1 || true)

    if echo "$result" | grep -q "speed="; then
        # Extract speed value (compatible with BSD/macOS grep)
        echo "$result" | sed -n 's/.*speed=\s*\([0-9.]*x\).*/\1/p' | tail -1
    else
        echo "FAIL"
    fi
}

# Run full test suite on a node
run_node_tests() {
    local node="$1"
    local quick="${2:-false}"
    local gpu_type=$(detect_node_gpu_type "$node")
    local job_name="${JOB_PREFIX}-${node}"

    header "Testing: $node ($gpu_type GPU)"

    # Create job
    if ! create_test_job "$node" "$gpu_type"; then
        log "${RED}Failed to create test job for $node${NC}"
        return 1
    fi

    local pod=$(get_job_pod "$job_name")
    if [[ -z "$pod" ]]; then
        log "${RED}No pod found for job${NC}"
        return 1
    fi

    # Show GPU info
    subheader "GPU Detection"
    case "$gpu_type" in
        intel|amd)
            kubectl exec -n "$NAMESPACE" "$pod" -- vainfo 2>&1 | grep -E "Driver|Profile" | head -10 || log "vainfo not available"
            ;;
        nvidia)
            kubectl exec -n "$NAMESPACE" "$pod" -- nvidia-smi --query-gpu=name,memory.total --format=csv,noheader 2>&1 || log "nvidia-smi not available"
            ;;
        cpu)
            log "CPU-only node (no GPU acceleration)"
            ;;
    esac

    # Determine encoders to test
    local hw_encoders=()
    local sw_encoders=("libx264" "libx265")

    case "$gpu_type" in
        intel)
            hw_encoders=("h264_qsv" "hevc_qsv" "av1_qsv")
            ;;
        amd)
            hw_encoders=("h264_vaapi" "hevc_vaapi")
            ;;
        nvidia)
            hw_encoders=("h264_nvenc" "hevc_nvenc" "av1_nvenc")
            ;;
        cpu)
            # CPU-only - no hardware encoders, just test software
            hw_encoders=()
            ;;
    esac

    # Run tests
    subheader "Encode Tests (1080p, ${TEST_DURATION}s)"
    printf "${CYAN}%-18s %-10s${NC}\n" "Encoder" "Speed"
    printf "%-18s %-10s\n" "--------" "-----"

    # Hardware encoders
    for encoder in "${hw_encoders[@]}"; do
        printf "%-18s " "$encoder"
        local speed=$(run_encode_test "$pod" "$encoder" "$gpu_type")
        if [[ "$speed" == "FAIL" ]]; then
            printf "${RED}%s${NC}\n" "FAIL"
        else
            printf "${GREEN}%s${NC}\n" "$speed"
        fi
    done

    # Software encoders (skip in quick mode)
    if [[ "$quick" != "true" ]]; then
        for encoder in "${sw_encoders[@]}"; do
            printf "%-18s " "$encoder"
            local speed=$(run_encode_test "$pod" "$encoder" "$gpu_type")
            if [[ "$speed" == "FAIL" ]]; then
                printf "${RED}%s${NC}\n" "FAIL"
            else
                printf "${YELLOW}%s${NC}\n" "$speed"
            fi
        done
    fi

    # Cleanup
    if [[ "$CLEANUP" == "true" ]]; then
        log "\n${CYAN}Cleaning up job...${NC}"
        kubectl delete job "$job_name" -n "$NAMESPACE" --ignore-not-found &>/dev/null
    fi
}

# Cleanup all test jobs
cleanup_jobs() {
    log "${CYAN}Cleaning up all test jobs...${NC}"
    kubectl delete jobs -n "$NAMESPACE" -l app=gpu-transcode-test --ignore-not-found
}

# Main
main() {
    local target_node=""
    local quick=false

    # Parse args
    while [[ $# -gt 0 ]]; do
        case "$1" in
            --node|-n)
                target_node="$2"
                shift 2
                ;;
            --quick|-q)
                quick=true
                shift
                ;;
            --cleanup)
                cleanup_jobs
                exit 0
                ;;
            --help|-h)
                cat <<EOF
GPU Transcode Test Script

Creates Kubernetes Jobs to test GPU encoding capabilities on each node.
Automatically discovers all nodes and tests hardware acceleration.

Usage:
  $0                          Test all nodes in the cluster
  $0 --node <node>            Test specific node
  $0 --quick                  Quick test (hardware encoders only)
  $0 --cleanup                Remove all test jobs

Options:
  --node, -n <node>    Target specific node (e.g., talos02-gpu)
  --quick, -q          Skip software encoder tests
  --cleanup            Remove leftover test jobs

Environment:
  CLEANUP=false        Keep jobs after completion (for debugging)
  TEST_DURATION=N      Encode test duration in seconds (default: 3)
  NAMESPACE=scratch    Namespace for test jobs (default: scratch)

GPU Types Detected:
  intel   - Intel QSV (h264_qsv, hevc_qsv, av1_qsv)
  amd     - AMD VAAPI (h264_vaapi, hevc_vaapi)
  nvidia  - NVIDIA NVENC (h264_nvenc, hevc_nvenc, av1_nvenc)
  cpu     - Software only (libx264, libx265)

Examples:
  $0                           # Test all nodes in cluster
  $0 --node talos02-gpu        # Test only Intel Arc node
  $0 --quick --node talos03    # Quick test AMD node
  CLEANUP=false $0             # Keep jobs for inspection
EOF
                exit 0
                ;;
            *)
                log "${RED}Unknown option: $1${NC}"
                exit 1
                ;;
        esac
    done

    header "GPU Transcode Test"
    log "Namespace: $NAMESPACE"
    log "Image: $IMAGE"
    log "Test Duration: ${TEST_DURATION}s"
    log "Quick Mode: $quick"

    if [[ -n "$target_node" ]]; then
        # Test single node
        run_node_tests "$target_node" "$quick"
    else
        # Test all nodes in the cluster
        local nodes=$(get_all_nodes)
        log "Discovered nodes: $(echo $nodes | tr '\n' ' ')"

        for node in $nodes; do
            run_node_tests "$node" "$quick"
        done
    fi

    header "Summary"
    log "Tests completed. Use ${CYAN}--cleanup${NC} to remove any leftover jobs."
}

main "$@"
