#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEPLOY_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
TEST_TMP="$(mktemp -d)"
trap 'rm -rf "$TEST_TMP"' EXIT

fail() { printf 'FAIL: %s\n' "$1" >&2; exit 1; }
assert_contains() { [[ "$1" == *"$2"* ]] || fail "expected to contain: $2"; }
assert_not_contains() { [[ "$1" != *"$2"* ]] || fail "expected NOT to contain: $2"; }
assert_valid_json() { printf '%s' "$1" | python3 -c 'import json,sys; json.load(sys.stdin)' || fail "invalid JSON: $1"; }

# Source the entrypoint's pure function without running the exec tail.
PI_ENTRYPOINT_TEST_SOURCE=1 source "$DEPLOY_DIR/docker/pi-entrypoint.sh"

# Neutralize any ambient model/base-url/key env so each case runs hermetically
# (a dev machine may export ANTHROPIC_MODEL / OPENAI_MODEL, etc.).
unset OPENAI_MODEL ANTHROPIC_MODEL OPENAI_BASE_URL ANTHROPIC_BASE_URL \
      OPENAI_API_KEY ANTHROPIC_API_KEY JOYSAFETER_MODEL_PROTOCOL

# --- openai_responses ---
out="$(JOYSAFETER_MODEL_PROTOCOL=openai_responses \
      OPENAI_MODEL=GPT-4.1 \
      OPENAI_BASE_URL=http://egress.local:3128/v1 \
      OPENAI_API_KEY=joysafeter-placeholder-openai-api-key \
      generate_pi_models_json)"
assert_valid_json "$out"
assert_contains "$out" '"openai-responses"'
assert_contains "$out" '"joysafeter"'
assert_contains "$out" '"GPT-4.1"'
assert_contains "$out" 'http://egress.local:3128/v1'
assert_contains "$out" '"$OPENAI_API_KEY"'
# The real key must never be baked in; only the placeholder ref is used.
assert_not_contains "$out" 'sk-'

# --- chat_completions (also verifies trailing slash is stripped from baseUrl:
#     pi appends /chat/completions, so a trailing slash would yield a // path
#     that the JD Cloud gateway rejects with 400) ---
out="$(JOYSAFETER_MODEL_PROTOCOL=chat_completions \
      OPENAI_MODEL=GPT-4.1 OPENAI_BASE_URL=http://egress.local:3128/v1/ \
      OPENAI_API_KEY=placeholder generate_pi_models_json)"
assert_contains "$out" '"openai-completions"'
assert_contains "$out" '"baseUrl": "http://egress.local:3128/v1"'
assert_not_contains "$out" 'v1/"'

# --- anthropic_messages ---
out="$(JOYSAFETER_MODEL_PROTOCOL=anthropic_messages \
      ANTHROPIC_MODEL=Claude-Opus-4.6 ANTHROPIC_BASE_URL=http://egress.local:3128 \
      ANTHROPIC_API_KEY=placeholder generate_pi_models_json)"
assert_valid_json "$out"
assert_contains "$out" '"anthropic-messages"'
assert_contains "$out" '"Claude-Opus-4.6"'
assert_contains "$out" '"$ANTHROPIC_API_KEY"'

# --- no model at all -> empty output, no file ---
out="$(JOYSAFETER_MODEL_PROTOCOL=custom generate_pi_models_json || true)"
[[ -z "$out" ]] || fail "expected empty output when no model configured"

printf 'pi-entrypoint regression tests passed\n'
