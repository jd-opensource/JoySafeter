#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEPLOY_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
TEST_TMP="$(mktemp -d)"
trap 'rm -rf "$TEST_TMP"' EXIT

fail() { printf 'FAIL: %s\n' "$1" >&2; exit 1; }

# shellcheck source=../docker/runtime-credentials.sh
source "$DEPLOY_DIR/docker/runtime-credentials.sh"

export JOYSAFETER_RUNTIME_SECRET_DIR="$TEST_TMP/secrets"
export JOYSAFETER_RUNNER_TOKEN="runner-session-token"
export JOYSAFETER_EGRESS_PROXY_TOKEN="egress-proxy-token"

prepare_runtime_credentials

[[ -z "${JOYSAFETER_RUNNER_TOKEN:-}" ]] || fail 'runner token env must be unset'
[[ -z "${JOYSAFETER_EGRESS_PROXY_TOKEN:-}" ]] || fail 'egress token env must be unset'
[[ "$(cat "$JOYSAFETER_RUNNER_TOKEN_FILE")" == 'runner-session-token' ]] \
    || fail 'runner token file mismatch'
[[ "$(cat "$JOYSAFETER_EGRESS_PROXY_TOKEN_FILE")" == 'egress-proxy-token' ]] \
    || fail 'egress token file mismatch'
[[ "$JOYSAFETER_RUNNER_TOKEN_FILE" != "$JOYSAFETER_EGRESS_PROXY_TOKEN_FILE" ]] \
    || fail 'purpose-specific credentials must use distinct files'

export JOYSAFETER_RUNNER_TOKEN="ambiguous"
if prepare_runtime_credentials 2>"$TEST_TMP/error"; then
    fail 'env and file sources together must be rejected'
fi
grep -q 'JOYSAFETER_RUNNER_TOKEN' "$TEST_TMP/error" \
    || fail 'ambiguous source error must identify runner credential'

printf 'runtime credential regression tests passed\n'
