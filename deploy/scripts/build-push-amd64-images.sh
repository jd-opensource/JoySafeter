#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
IMAGE_PROFILE="${IMAGE_PROFILE:-sandbox-plane}"
REGISTRY="${DOCKER_REGISTRY:-${REGISTRY_PREFIX:-aisec-repo.jd.com/joysafeter}}"
TAG="${TAG:-${IMAGE_TAG:-latest}}"

selection_args=()
forward_args=()
command=push
mode_args=(--plain)
explicit_selection=false

case "${SKIP_PUSH:-0}" in
    1|true)
        command=build
        mode_args=()
        ;;
esac

case "${NO_CACHE:-0}" in
    1|true)
        forward_args+=(--no-cache)
        ;;
esac

append_target() {
    local target=$1
    case "$target" in
        orchestrator|orchestrator-rs|orchestrator_rs)
            selection_args+=(--component orchestrator)
            ;;
        claudecode|codex|native|pi|skillspector)
            selection_args+=(--component "$target")
            ;;
        all)
            selection_args+=(
                --component orchestrator
                --component native
                --component pi
            )
            ;;
        "")
            ;;
        *)
            return 1
            ;;
    esac
}

while [ "$#" -gt 0 ]; do
    case "$1" in
        --component|--group|--profile)
            [ "$#" -ge 2 ] || { printf 'missing value for %s\n' "$1" >&2; exit 1; }
            explicit_selection=true
            forward_args+=("$1" "$2")
            shift 2
            ;;
        --registry|-r|--tag|-t|--platform|--arch|--family|--format|--mirror|--pip-mirror|--api-url)
            [ "$#" -ge 2 ] || { printf 'missing value for %s\n' "$1" >&2; exit 1; }
            forward_args+=("$1" "$2")
            shift 2
            ;;
        --)
            shift
            while [ "$#" -gt 0 ]; do
                forward_args+=("$1")
                shift
            done
            ;;
        *)
            if ! append_target "$1"; then
                forward_args+=("$1")
            fi
            shift
            ;;
    esac
done

if [ "${#selection_args[@]}" -eq 0 ] && [ -n "${TARGETS:-${IMAGES:-}}" ]; then
    legacy_targets="${TARGETS:-${IMAGES:-}}"
    legacy_targets="${legacy_targets//,/ }"
    for arg in $legacy_targets; do
        if ! append_target "$arg"; then
            printf 'unknown target: %s\n' "$arg" >&2
            exit 1
        fi
    done
fi

if [ "${#selection_args[@]}" -eq 0 ] && [ "$explicit_selection" = false ]; then
    selection_args=(--profile "$IMAGE_PROFILE")
fi

if [ -n "${REPO:-}" ] && [ -z "${DOCKER_REGISTRY:-}${REGISTRY_PREFIX:-}" ]; then
    REGISTRY="${REPO%/*}"
fi

exec "$REPO_ROOT/deploy/deploy.sh" "$command" \
    ${selection_args[@]+"${selection_args[@]}"} \
    --arch amd64 \
    ${mode_args[@]+"${mode_args[@]}"} \
    --registry "$REGISTRY" \
    --tag "$TAG" \
    ${forward_args[@]+"${forward_args[@]}"}
