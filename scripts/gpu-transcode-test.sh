#!/usr/bin/env bash
#
# GPU Transcode Test Script
# Discovers GPUs in the cluster and runs encode/decode matrix tests
#
# Usage: ./scripts/gpu-transcode-test.sh [namespace]
#

set -euo pipefail

NAMESPACE="${1:-media}"
REPORT_FILE="/tmp/gpu-transcode-report-$(date +%Y%m%d-%H%M%S).txt"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Test duration in seconds
TEST_DURATION=2

# Codecs to test
DECODE_CODECS=("h264" "hevc" "vp9" "av1")
ENCODE_CODECS_QSV=("h264_qsv" "hevc_qsv" "av1_qsv")
ENCODE_CODECS_VAAPI=("h264_vaapi" "hevc_vaapi" "av1_vaapi")
ENCODE_CODECS_SOFTWARE=("libx264" "libx265" "libsvtav1")

log() {
    echo -e "$1" | tee -a "$REPORT_FILE"
}

header() {
    log ""
    log "${BLUE}═══════════════════════════════════════════════════════════════${NC}"
    log "${BLUE}  $1${NC}"
    log "${BLUE}═══════════════════════════════════════════════════════════════${NC}"
}

subheader() {
    log ""
    log "${YELLOW}--- $1 ---${NC}"
}

# Discover GPU-capable pods
discover_gpu_pods() {
    log "Discovering GPU-capable pods in namespace: $NAMESPACE"

    # Find pods with /dev/dri mounted
    kubectl get pods -n "$NAMESPACE" -o json | jq -r '
        .items[] |
        select(.status.phase == "Running") |
        select(.spec.volumes[]?.hostPath?.path == "/dev/dri" or
               .spec.containers[].volumeMounts[]?.mountPath == "/dev/dri") |
        .metadata.name
    ' 2>/dev/null || true
}

# Get GPU info from a pod
get_gpu_info() {
    local pod="$1"
    local info=""

    # Try vainfo first (Intel/AMD VAAPI)
    info=$(kubectl exec -n "$NAMESPACE" "$pod" -- vainfo 2>&1 | grep -E "Driver version|Supported profile" | head -20 || true)

    if [[ -n "$info" ]]; then
        echo "$info"
        return
    fi

    # Check for device files
    kubectl exec -n "$NAMESPACE" "$pod" -- ls -la /dev/dri/ 2>/dev/null || echo "No /dev/dri access"
}

# Detect GPU type (intel, amd, nvidia, none)
detect_gpu_type() {
    local pod="$1"

    local vainfo=$(kubectl exec -n "$NAMESPACE" "$pod" -- vainfo 2>&1 || true)

    if echo "$vainfo" | grep -qi "iHD\|Intel"; then
        echo "intel"
    elif echo "$vainfo" | grep -qi "radeon\|amdgpu\|AMD"; then
        echo "amd"
    elif kubectl exec -n "$NAMESPACE" "$pod" -- ls /dev/nvidia0 &>/dev/null; then
        echo "nvidia"
    else
        echo "software"
    fi
}

# Run single encode test
run_encode_test() {
    local pod="$1"
    local encoder="$2"
    local hw_device="$3"

    local cmd=""
    local result=""
    local speed=""

    case "$encoder" in
        *_qsv)
            cmd="ffmpeg -hide_banner -y -init_hw_device qsv=hw -filter_hw_device hw -f lavfi -i testsrc=duration=${TEST_DURATION}:size=1920x1080:rate=30 -vf 'format=nv12,hwupload=extra_hw_frames=64' -c:v $encoder -preset fast -f null -"
            ;;
        *_vaapi)
            cmd="ffmpeg -hide_banner -y -vaapi_device /dev/dri/renderD128 -f lavfi -i testsrc=duration=${TEST_DURATION}:size=1920x1080:rate=30 -vf 'format=nv12,hwupload' -c:v $encoder -f null -"
            ;;
        *_nvenc)
            cmd="ffmpeg -hide_banner -y -hwaccel cuda -f lavfi -i testsrc=duration=${TEST_DURATION}:size=1920x1080:rate=30 -c:v $encoder -preset fast -f null -"
            ;;
        lib*)
            cmd="ffmpeg -hide_banner -y -f lavfi -i testsrc=duration=${TEST_DURATION}:size=1920x1080:rate=30 -c:v $encoder -preset fast -f null -"
            ;;
        *)
            cmd="ffmpeg -hide_banner -y -f lavfi -i testsrc=duration=${TEST_DURATION}:size=1920x1080:rate=30 -c:v $encoder -f null -"
            ;;
    esac

    result=$(kubectl exec -n "$NAMESPACE" "$pod" -- bash -c "$cmd" 2>&1 || true)

    if echo "$result" | grep -q "speed="; then
        speed=$(echo "$result" | sed -n 's/.*speed=\s*\([0-9.]*x\).*/\1/p' | tail -1)
        echo "$speed"
    else
        echo "FAIL"
    fi
}

# Run decode test
run_decode_test() {
    local pod="$1"
    local decoder="$2"
    local hw_accel="$3"

    local cmd=""
    local result=""
    local speed=""

    # Generate test source and decode
    case "$hw_accel" in
        qsv)
            cmd="ffmpeg -hide_banner -y -init_hw_device qsv=hw -hwaccel qsv -hwaccel_output_format qsv -f lavfi -i testsrc=duration=${TEST_DURATION}:size=1920x1080:rate=30 -c:v libx264 -f matroska - | ffmpeg -hide_banner -y -init_hw_device qsv=hw -hwaccel qsv -c:v ${decoder}_qsv -i - -f null -"
            ;;
        vaapi)
            cmd="ffmpeg -hide_banner -y -f lavfi -i testsrc=duration=${TEST_DURATION}:size=1920x1080:rate=30 -c:v libx264 -f matroska - | ffmpeg -hide_banner -y -vaapi_device /dev/dri/renderD128 -hwaccel vaapi -i - -f null -"
            ;;
        *)
            # Software decode test
            cmd="ffmpeg -hide_banner -y -f lavfi -i testsrc=duration=${TEST_DURATION}:size=1920x1080:rate=30 -c:v libx264 -f matroska - | ffmpeg -hide_banner -y -i - -f null -"
            ;;
    esac

    result=$(kubectl exec -n "$NAMESPACE" "$pod" -- bash -c "$cmd" 2>&1 || true)

    if echo "$result" | grep -q "speed="; then
        speed=$(echo "$result" | sed -n 's/.*speed=\s*\([0-9.]*x\).*/\1/p' | tail -1)
        echo "$speed"
    else
        echo "FAIL"
    fi
}

# Generate encode matrix for a pod
generate_encode_matrix() {
    local pod="$1"
    local gpu_type="$2"

    subheader "Encode Tests"

    local encoders=()

    case "$gpu_type" in
        intel)
            encoders=("${ENCODE_CODECS_QSV[@]}" "${ENCODE_CODECS_SOFTWARE[@]}")
            ;;
        amd)
            encoders=("${ENCODE_CODECS_VAAPI[@]}" "${ENCODE_CODECS_SOFTWARE[@]}")
            ;;
        *)
            encoders=("${ENCODE_CODECS_SOFTWARE[@]}")
            ;;
    esac

    printf "%-20s %s\n" "Encoder" "Speed" | tee -a "$REPORT_FILE"
    printf "%-20s %s\n" "-------" "-----" | tee -a "$REPORT_FILE"

    for encoder in "${encoders[@]}"; do
        local speed=$(run_encode_test "$pod" "$encoder" "$gpu_type")
        if [[ "$speed" == "FAIL" ]]; then
            printf "%-20s ${RED}%s${NC}\n" "$encoder" "FAIL" | tee -a "$REPORT_FILE"
        else
            printf "%-20s ${GREEN}%s${NC}\n" "$encoder" "$speed" | tee -a "$REPORT_FILE"
        fi
    done
}

# Main report generation
generate_report() {
    header "GPU Transcode Test Report"
    log "Generated: $(date)"
    log "Namespace: $NAMESPACE"

    # Get cluster info
    subheader "Cluster Nodes"
    kubectl get nodes -o wide --no-headers | while read line; do
        log "  $line"
    done

    # Discover GPU pods
    header "GPU-Capable Pods Discovery"

    local pods=$(discover_gpu_pods)

    if [[ -z "$pods" ]]; then
        log "${YELLOW}No GPU-capable pods found in namespace $NAMESPACE${NC}"
        log "Looking for any pod with ffmpeg..."
        pods=$(kubectl get pods -n "$NAMESPACE" -o jsonpath='{.items[?(@.status.phase=="Running")].metadata.name}' | tr ' ' '\n' | head -5)
    fi

    for pod in $pods; do
        header "Pod: $pod"

        # Get node
        local node=$(kubectl get pod -n "$NAMESPACE" "$pod" -o jsonpath='{.spec.nodeName}')
        log "Node: $node"

        # Detect GPU type
        local gpu_type=$(detect_gpu_type "$pod")
        log "GPU Type: $gpu_type"

        # Get GPU info
        subheader "GPU Info (vainfo)"
        local gpu_info=$(get_gpu_info "$pod")
        echo "$gpu_info" | head -15 | tee -a "$REPORT_FILE"

        # Check available devices
        subheader "Device Files"
        kubectl exec -n "$NAMESPACE" "$pod" -- ls -la /dev/dri/ 2>/dev/null | tee -a "$REPORT_FILE" || log "No /dev/dri access"

        # Run encode matrix
        generate_encode_matrix "$pod" "$gpu_type"

    done

    # Summary
    header "Summary"
    log "Report saved to: $REPORT_FILE"
}

# Quick test mode - just test one pod
quick_test() {
    local pod="$1"

    echo "Quick GPU test for pod: $pod"
    echo ""

    # Detect GPU
    local gpu_type=$(detect_gpu_type "$pod")
    echo "GPU Type: $gpu_type"
    echo ""

    # Quick encode tests
    echo "Running quick encode tests..."
    echo ""

    case "$gpu_type" in
        intel)
            echo -n "h264_qsv: "
            run_encode_test "$pod" "h264_qsv" "qsv"
            echo -n "hevc_qsv: "
            run_encode_test "$pod" "hevc_qsv" "qsv"
            echo -n "av1_qsv:  "
            run_encode_test "$pod" "av1_qsv" "qsv"
            ;;
        amd)
            echo -n "h264_vaapi: "
            run_encode_test "$pod" "h264_vaapi" "vaapi"
            echo -n "hevc_vaapi: "
            run_encode_test "$pod" "hevc_vaapi" "vaapi"
            ;;
        *)
            echo -n "libx264: "
            run_encode_test "$pod" "libx264" ""
            echo -n "libx265: "
            run_encode_test "$pod" "libx265" ""
            ;;
    esac
}

# Parse arguments
case "${1:-}" in
    --quick)
        if [[ -z "${2:-}" ]]; then
            echo "Usage: $0 --quick <pod-name> [namespace]"
            exit 1
        fi
        NAMESPACE="${3:-media}"
        quick_test "$2"
        ;;
    --help|-h)
        echo "GPU Transcode Test Script"
        echo ""
        echo "Usage:"
        echo "  $0 [namespace]           Run full report (default namespace: media)"
        echo "  $0 --quick <pod> [ns]    Quick test single pod"
        echo "  $0 --help                Show this help"
        echo ""
        echo "Examples:"
        echo "  $0                       # Full report for 'media' namespace"
        echo "  $0 arr-stack             # Full report for 'arr-stack' namespace"
        echo "  $0 --quick tdarr-xxx     # Quick test specific pod"
        ;;
    *)
        generate_report
        ;;
esac
