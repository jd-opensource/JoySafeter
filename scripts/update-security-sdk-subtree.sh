#!/usr/bin/env bash

set -euo pipefail

REMOTE_NAME="${SECURITY_SDK_REMOTE_NAME:-claude-sdk-upstream}"
REMOTE_URL="${SECURITY_SDK_REMOTE_URL:-https://github.com/anthropics/claude-agent-sdk-python.git}"
PREFIX="backend/app/one_person_security_dept/claude_agent_sdk_python/claude-agent-sdk-python"
REF="main"
SETUP_ONLY=0
DRY_RUN=0
SQUASH=1

usage() {
  cat <<'EOF'
Usage:
  update-security-sdk-subtree.sh [options]

Options:
  --ref <ref>         Upstream ref to update from (tag or branch). Default: main
  --setup-only        Only ensure remote exists, do not pull
  --dry-run           Print planned commands without executing subtree pull
  --no-squash         Do not use --squash during subtree pull
  -h, --help          Show this help

Environment variables:
  SECURITY_SDK_REMOTE_NAME   Remote name (default: claude-sdk-upstream)
  SECURITY_SDK_REMOTE_URL    Remote URL
                             (default: https://github.com/anthropics/claude-agent-sdk-python.git)

Examples:
  ./scripts/update-security-sdk-subtree.sh --setup-only
  ./scripts/update-security-sdk-subtree.sh --ref v0.1.43
  ./scripts/update-security-sdk-subtree.sh --ref main --dry-run
EOF
}

ensure_repo_root() {
  local repo_root
  repo_root="$(git rev-parse --show-toplevel 2>/dev/null || true)"
  if [[ -z "${repo_root}" ]]; then
    echo "Error: not inside a git repository." >&2
    exit 1
  fi
  cd "${repo_root}"
}

ensure_remote() {
  if git remote get-url "${REMOTE_NAME}" >/dev/null 2>&1; then
    local current_url
    current_url="$(git remote get-url "${REMOTE_NAME}")"
    if [[ "${current_url}" != "${REMOTE_URL}" ]]; then
      echo "Error: remote '${REMOTE_NAME}' already exists with different URL:" >&2
      echo "  current: ${current_url}" >&2
      echo "  expect : ${REMOTE_URL}" >&2
      echo "Fix it manually or set SECURITY_SDK_REMOTE_NAME/SECURITY_SDK_REMOTE_URL." >&2
      exit 1
    fi
    return
  fi

  git remote add "${REMOTE_NAME}" "${REMOTE_URL}"
}

ensure_clean_worktree() {
  if ! git diff --quiet || ! git diff --cached --quiet; then
    echo "Error: working tree has local changes. Commit or stash before subtree pull." >&2
    exit 1
  fi
}

parse_args() {
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --ref)
        if [[ $# -lt 2 ]]; then
          echo "Error: --ref requires a value." >&2
          exit 1
        fi
        REF="$2"
        shift 2
        ;;
      --setup-only)
        SETUP_ONLY=1
        shift
        ;;
      --dry-run)
        DRY_RUN=1
        shift
        ;;
      --no-squash)
        SQUASH=0
        shift
        ;;
      -h|--help)
        usage
        exit 0
        ;;
      *)
        echo "Error: unknown option '$1'." >&2
        usage
        exit 1
        ;;
    esac
  done
}

main() {
  parse_args "$@"
  ensure_repo_root
  ensure_remote

  echo "Remote: ${REMOTE_NAME} (${REMOTE_URL})"
  echo "Prefix: ${PREFIX}"
  echo "Ref   : ${REF}"

  if [[ "${SETUP_ONLY}" -eq 1 ]]; then
    echo "Setup complete."
    return
  fi

  if [[ ! -d "${PREFIX}" ]]; then
    echo "Error: subtree prefix does not exist: ${PREFIX}" >&2
    exit 1
  fi

  local cmd=(git subtree pull --prefix="${PREFIX}" "${REMOTE_NAME}" "${REF}")
  if [[ "${SQUASH}" -eq 1 ]]; then
    cmd+=(--squash)
  fi

  if [[ "${DRY_RUN}" -eq 1 ]]; then
    echo "[dry-run] ${cmd[*]}"
    return
  fi

  ensure_clean_worktree
  git fetch "${REMOTE_NAME}" --tags
  "${cmd[@]}"
}

main "$@"
