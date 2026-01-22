#!/usr/bin/env bash
#
# Script Discovery Tool
#
# Lists all scripts organized by namespace/stack hierarchy.
# Scripts can live at multiple levels:
#   - scripts/                          (repo-level)
#   - infrastructure/base/*/scripts/    (infra stacks)
#   - applications/*/base/scripts/      (app stacks)
#   - clusters/*/scripts/               (cluster-specific)
#
# Usage:
#   ./scripts/list-scripts.sh           # List all scripts
#   ./scripts/list-scripts.sh --run     # Interactive mode (fzf)
#   ./scripts/list-scripts.sh <pattern> # Filter by pattern
#
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

# Colors
CYAN='\033[0;36m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
DIM='\033[2m'
BOLD='\033[1m'
NC='\033[0m'

# Parse args
PATTERN=""
RUN_MODE=false
for arg in "$@"; do
    case $arg in
        --run|-r) RUN_MODE=true ;;
        --help|-h)
            echo "Usage: $0 [--run] [pattern]"
            echo "  --run, -r   Interactive mode with fzf"
            echo "  pattern     Filter scripts by pattern"
            exit 0
            ;;
        *) PATTERN="$arg" ;;
    esac
done

# Find all scripts
find_scripts() {
    local scripts=()

    # Repo-level scripts (excluding this discovery script)
    while IFS= read -r -d '' script; do
        [[ "$(basename "$script")" == "list-scripts.sh" ]] && continue
        scripts+=("$script")
    done < <(find "$REPO_ROOT/scripts" -maxdepth 1 -name "*.sh" -type f -print0 2>/dev/null || true)

    # Infrastructure stack scripts
    while IFS= read -r -d '' script; do
        scripts+=("$script")
    done < <(find "$REPO_ROOT/infrastructure/base" -path "*/scripts/*.sh" -type f -print0 2>/dev/null || true)

    # Application stack scripts (exclude node_modules, vendor, etc)
    while IFS= read -r -d '' script; do
        scripts+=("$script")
    done < <(find "$REPO_ROOT/applications" -path "*/scripts/*.sh" -type f \
        -not -path "*/node_modules/*" \
        -not -path "*/vendor/*" \
        -not -path "*/.venv/*" \
        -print0 2>/dev/null || true)

    # Cluster-specific scripts
    while IFS= read -r -d '' script; do
        scripts+=("$script")
    done < <(find "$REPO_ROOT/clusters" -path "*/scripts/*.sh" -type f -print0 2>/dev/null || true)

    # Sort and optionally filter
    for script in "${scripts[@]}"; do
        local rel_path="${script#$REPO_ROOT/}"
        if [[ -z "$PATTERN" ]] || [[ "$rel_path" == *"$PATTERN"* ]]; then
            echo "$rel_path"
        fi
    done | sort
}

# Get script description from first comment block
get_description() {
    local script="$1"
    local desc=""
    # Look for first non-empty comment line after shebang (skip blank # lines)
    desc=$(awk '
        NR > 1 && /^#/ {
            sub(/^#+ */, "")
            if (length($0) > 0 && $0 !~ /^!/) {
                print
                exit
            }
        }
        NR > 1 && !/^#/ && !/^[[:space:]]*$/ { exit }
    ' "$REPO_ROOT/$script" 2>/dev/null)

    if [[ -n "$desc" && ${#desc} -gt 3 ]]; then
        # Truncate long descriptions
        if [[ ${#desc} -gt 60 ]]; then
            echo "${desc:0:57}..."
        else
            echo "$desc"
        fi
    else
        echo "${DIM}(no description)${NC}"
    fi
}

# Categorize script by path
get_category() {
    local script="$1"
    case "$script" in
        scripts/*) echo "repo" ;;
        infrastructure/base/*/scripts/*)
            echo "infra/$(echo "$script" | cut -d'/' -f3)"
            ;;
        applications/*/base/scripts/*)
            echo "apps/$(echo "$script" | cut -d'/' -f2)"
            ;;
        applications/*/scripts/*)
            echo "apps/$(echo "$script" | cut -d'/' -f2)"
            ;;
        clusters/*/scripts/*)
            echo "clusters/$(echo "$script" | cut -d'/' -f2)"
            ;;
        *) echo "other" ;;
    esac
}

# Display scripts in tree format
display_tree() {
    local scripts=("$@")
    local current_category=""

    echo ""
    echo -e "${BOLD}╔══════════════════════════════════════════════════════════════╗${NC}"
    echo -e "${BOLD}║                    Available Scripts                         ║${NC}"
    echo -e "${BOLD}╚══════════════════════════════════════════════════════════════╝${NC}"
    echo ""

    for script in "${scripts[@]}"; do
        local category
        category=$(get_category "$script")

        # Print category header if changed
        if [[ "$category" != "$current_category" ]]; then
            current_category="$category"
            echo ""
            case "$category" in
                repo)
                    echo -e "${CYAN}📁 Repository Scripts${NC}"
                    ;;
                infra/*)
                    local stack="${category#infra/}"
                    echo -e "${CYAN}🔧 Infrastructure: ${BOLD}${stack}${NC}"
                    ;;
                apps/*)
                    local stack="${category#apps/}"
                    echo -e "${CYAN}📦 Application: ${BOLD}${stack}${NC}"
                    ;;
                clusters/*)
                    local cluster="${category#clusters/}"
                    echo -e "${CYAN}☸️  Cluster: ${BOLD}${cluster}${NC}"
                    ;;
                *)
                    echo -e "${CYAN}📄 Other${NC}"
                    ;;
            esac
            echo -e "${DIM}────────────────────────────────────────${NC}"
        fi

        # Print script entry
        local name
        name=$(basename "$script" .sh)
        local desc
        desc=$(get_description "$script")
        echo -e "  ${GREEN}${name}${NC}"
        echo -e "    ${DIM}${script}${NC}"
        echo -e "    ${desc}"
    done

    echo ""
    echo -e "${DIM}Run a script: ./<path-to-script>${NC}"
    echo -e "${DIM}Interactive:  $0 --run${NC}"
    echo ""
}

# Interactive mode with fzf
run_interactive() {
    local scripts=("$@")

    if ! command -v fzf &>/dev/null; then
        echo "Error: fzf not installed. Install with: brew install fzf"
        exit 1
    fi

    local selected
    selected=$(printf '%s\n' "${scripts[@]}" | fzf \
        --preview "head -30 $REPO_ROOT/{}" \
        --preview-window=right:50%:wrap \
        --header="Select a script to run (ESC to cancel)" \
        --prompt="Script > ")

    if [[ -n "$selected" ]]; then
        echo ""
        echo -e "${YELLOW}Running: ${selected}${NC}"
        echo ""
        "$REPO_ROOT/$selected"
    fi
}

# Main
main() {
    local scripts
    mapfile -t scripts < <(find_scripts)

    if [[ ${#scripts[@]} -eq 0 ]]; then
        echo "No scripts found"
        exit 0
    fi

    if $RUN_MODE; then
        run_interactive "${scripts[@]}"
    else
        display_tree "${scripts[@]}"
    fi
}

main
